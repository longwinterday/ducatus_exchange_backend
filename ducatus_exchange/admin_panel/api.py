import sys
import traceback

from bip32utils import BIP32Key
from eth_keys import keys
from eth_account import Account
from rest_framework.exceptions import NotFound

from ducatus_exchange.bip32_ducatus import DucatusWallet
from ducatus_exchange.litecoin_rpc import DucatuscoreInterface
from ducatus_exchange.parity_interface import ParityInterface
from ducatus_exchange.payments.models import Payment
from ducatus_exchange.consts import CURRENCIES, DECIMALS
from ducatus_exchange.settings import ROOT_KEYS, COLLECTION_ADDRESSES, IS_TESTNET_PAYMENTS, NETWORK_SETTINGS


class LowBalance(Exception):
    pass


class InterfaceError(Exception):
    pass


def get_input_balance():
    res = {}
    for currency in CURRENCIES:
        amounts = Payment.objects.filter(collection_state='NOT_COLLECTED', currency=currency).values_list(
            'original_amount', flat=True)
        res[currency] = sum(amounts)

    return res


def get_output_balance():
    btc_interface = DucatuscoreInterface()
    duc_balance = btc_interface.rpc.getbalance('')

    eth_interface = ParityInterface('DUCX')
    ducx_balance = int(eth_interface.eth_getBalance(NETWORK_SETTINGS['DUCX']['address']), 16)

    res = {
        'DUC': duc_balance * DECIMALS['DUC'],
        'DUCX': ducx_balance,
    }

    return res


def withdraw_coins(currency):
    payments = Payment.objects.filter(collection_state='NOT_COLLECTED', currency=currency)

    if currency in ['ETH', 'DUCX']:
        for payment in payments:
            try:
                collect_eth(payment)
            except (LowBalance, InterfaceError):
                payment.collection_state = 'ERROR'
                payment.save()
                print('\n'.join(traceback.format_exception(*sys.exc_info())), flush=True)
    elif currency in ['DUC', 'BTC']:
        pass
    else:
        raise NotFound


def collect_parity(payment: Payment, currency: str):
    if currency == 'ETH':
        net_name = 'testnet' if IS_TESTNET_PAYMENTS else 'mainnet'
    elif currency == 'DUCX':
        net_name = 'ducatusx'
    else:
        print(f'currency {currency} not supported', flush=True)
        return

    x = BIP32Key.fromExtendedKey(ROOT_KEYS[net_name]['private'])

    child_private = keys.PrivateKey(x.ChildKey(payment.exchange_request.user.id).k.to_string())
    amount = payment.original_amount
    address = payment.exchange_request.eth_address

    interface = ParityInterface(currency)

    interface.raw_transfer()

    if int(interface.eth_getBalance(payment.exchange_request.eth_address), 16) < amount:
        raise LowBalance

    gas_price = int(interface.eth_gasPrice(), 16)
    gas = 21000

    tx = {
        'gasPrice': gas_price,
        'gas': gas,
        'to': COLLECTION_ADDRESSES[currency],
        'nonce': interface.eth_getTransactionCount(address, 'pending'),
        'value': int(amount - gas * gas_price),
    }

    signed = Account.sign_transaction(tx, child_private)

    print('try collect {amount} {currency} from payment {payment_id}'.format(amount=tx['value'],
                                                                             currency=currency,
                                                                             payment_id=payment.id),
          flush=True)
    try:
        tx_hash = interface.eth_sendRawTransaction(signed.rawTransaction.hex())
        print('tx hash', tx_hash, flush=True)
    except Exception:
        raise InterfaceError

    payment.collection_state = 'WAITING_FOR_CONFIRMATION'
    payment.collection_tx_hash = tx_hash
    payment.save()
