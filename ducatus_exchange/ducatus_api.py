import requests
import datetime
from decimal import Decimal

from ducatus_exchange.transfers.models import DucatusTransfer
from ducatus_exchange.payments.models import Payment
from ducatus_exchange.consts import DECIMALS
from ducatus_exchange.litecoin_rpc import DucatuscoreInterface
from ducatus_exchange.bip32_ducatus import DucatusWallet
from ducatus_exchange.settings import ROOT_KEYS, STATS_NORMALIZED_TIME

class DucatusAPI:

    def __init__(self):
        self.network = 'mainnet'
        self.base_url = None
        self.set_base_url()

    def set_base_url(self):
        self.base_url = f'https://ducapi.rocknblock.io/api/DUC/{self.network}'

    def get_address_response(self, address):
        endpoint_url = f'{self.base_url}/address/{address}'
        res = requests.get(endpoint_url)
        if not res.ok:
            return [], False
        else:
            valid_json = len(res.json()) > 0
            if not valid_json:
                print('Address have no transactions and balance is 0', flush=True)
                return [], True

            return res.json(), True

    def get_address_unspent_all(self, address):
        inputs_of_address, response_ok = self.get_address_response(address)
        if not response_ok:
            return [], 0, False

        if response_ok and len(inputs_of_address) == 0:
            return inputs_of_address, 0, True

        inputs_value = 0
        unspent_inputs = []
        for input_tx in inputs_of_address:
            if not input_tx['spentTxid']:
                unspent_inputs.append({
                    'txid': input_tx['mintTxid'],
                    'vout': input_tx['mintIndex']
                })
                inputs_value += input_tx['value']

        return unspent_inputs, inputs_value, True

    def get_address_unspent_from_tx(self, address, tx_hash):
        inputs_of_address, response_ok = self.get_address_response(address)
        if not response_ok:
            return [], 0, False

        if response_ok and len(inputs_of_address) == 0:
            return inputs_of_address, 0, True

        # find vout
        vout = None
        input_value = 0
        for input_tx in inputs_of_address:
            if not input_tx['spentTxid'] and input_tx['mintTxid'] == tx_hash:
                vout = input_tx['mintIndex']
                input_value = input_tx['value']

        if vout is None:
            return [], 0, False

        input_params = [{'txid': tx_hash, 'vout': vout}]
        return input_params, input_value, True

    def get_return_address(self, tx_hash):
        endpoint_url = f'{self.base_url}/tx/{tx_hash}/coins'
        res = requests.get(endpoint_url)
        if not res.ok:
            return '', False, res
        else:
            tx_info = res.json()

        inputs_of_tx = tx_info['inputs']
        if len(inputs_of_tx) == 0:
            return '', False, res

        first_input = inputs_of_tx[0]
        return_address = first_input['address']

        address_found = False
        if return_address:
            address_found = True

        return return_address, address_found, res

    def get_last_blockchain_block(self):
        req_string = f'{self.base_url}/block/tip'
        res = requests.get(req_string)
        data = res.json()
        blockchain_last_block = data["height"]
        return blockchain_last_block

    def get_block_transactions(self, block_number):
        req_string = f'{self.base_url}/tx?blockHeight=' + str(block_number)
        print(f'block transaction string: {req_string}')
        res = requests.get(req_string)
        data = res.json()

        sending_transactions = []
        for tx in data:
            if tx.get('value') not in (0, -1):
                sending_transactions.append(tx)

        return sending_transactions

    # def get_transactions_from_blocks(self, now_block, scan_until_block):
    #     txs = []
    #     current_block = now_block
    #
    #     while current_block <= scan_until_block:
    #         txs_in_block = self.get_block_transactions(current_block)
    #         if len(txs_in_block) > 0:
    #             for transaction in txs_in_block:
    #                 txs.append(transaction)
    #
    #         print(f'Block: {current_block}, tx count: {len(txs)}')
    #         current_block += 1
    #
    #     return txs

    def get_tx_value(self, tx):
        tx_id = tx.get('txid')
        return_address, found, tx_request = self.get_return_address(tx_id)

        if found:
            value = 0
            for output in tx_request.json().get('outputs'):
                if output.get('address') != return_address:
                    value += int(output.get('value'))
        else:
            value = tx.get('value')

        return value

    def get_last_block_time(self, block):
        req_string = f'{self.base_url}/block/{block}'
        res = requests.get(req_string)
        data = res.json()
        time = data.get('time')
        time_date = datetime.datetime.strptime(time, STATS_NORMALIZED_TIME)
        return time_date

    def get_address_balance(self, address):
        req_string = f'{self.base_url}/address/{address}/balance'
        # print(f'address balance string {req_string}', flush=True)
        res = requests.get(req_string)
        data = res.json()
        balance = int(float(data.get('balance')))
        return balance

    def get_transaction_by_hash(self, tx_hash):
        req_string = f'{self.base_url}/tx/{tx_hash}'
        res = requests.get(req_string)
        data = res.json()
        return data


class DucatusXAPI(DucatusAPI):
    def set_base_url(self):
        self.base_url = f'https://ducapi.rocknblock.io/api/DUCX/{self.network}'

    def get_tx_value(self, tx):
        return tx.get('value')


def return_ducatus(payment_hash, amount):
    p = Payment.objects.get(tx_hash=payment_hash)

    duc_root_key = DucatusWallet.deserialize(ROOT_KEYS['ducatus']['private'])
    duc_child = duc_root_key.get_child(p.exchange_request.user.id, is_prime=False)
    child_private = duc_child.export_to_wif().decode()

    # if p.transfer_state in ['ERROR', 'WAITING_FOR_TRANSFER']:
    #     amount = p.original_amount
    # elif p.transfer_state == 'DONE':
    #     orig_duc_amount = p.original_amount
    #
    #     dt = DucatusTransfer.objects.get(payment=p)
    #     sent_ducx_amount = dt.amount
    #
    #     if (sent_ducx_amount / DECIMALS['DUCX']) < (orig_duc_amount / DECIMALS['DUC'] / 10):
    #         amount =
    # else:
    #     print('state not defined:', p.transfer_state, flush=True)
    #     return

    duc_api = DucatusAPI()
    duc_rpc = DucatuscoreInterface()

    raw_fee = duc_rpc.get_fee()
    fee = raw_fee * DECIMALS['DUC']
    raw_send_amount = amount - fee
    send_amount = Decimal(raw_send_amount) / DECIMALS['DUC']

    input_params, input_value, response_ok = duc_api.get_address_unspent_from_tx(p.exchange_request.duc_address, p.tx_hash)
    if not response_ok:
        print('fail to fetch input param', flush=True)
        return

    print('input_params', input_params, flush=True)

    return_address, response_ok, return_res = duc_api.get_return_address(p.tx_hash)
    if not response_ok:
        print('fail to fetch return address', flush=True)
        return
    
    if return_address==p.exchange_request.duc_address:
        print('returning address is equal to receive address, cancelling return to avoid loop')
        return
    
    output_params = {return_address: send_amount}
    if amount < input_value:

        output_params[p.exchange_request.duc_address] = (input_value - fee - raw_send_amount) / DECIMALS['DUC']

    print('output_params', output_params, flush=True)

    tx = duc_rpc.rpc.createrawtransaction(input_params, output_params)
    print('raw tx', tx, flush=True)

    signed = duc_rpc.rpc.signrawtransaction(tx, None, [child_private])
    print('signed tx', signed, flush=True)

    tx_hash = duc_rpc.rpc.sendrawtransaction(signed['hex'])
    print('tx', tx_hash, flush=True)
    print('receive address was:', p.exchange_request.duc_address, flush=True)
