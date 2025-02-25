"""inkassation will not work with ERC20 tokens (needs integration with backend architecure and non-standart UsdRates.
Inkassation will not work with DUC (not implemented),
DUCX (needs integration with both ExchangeRequest and DucatusUser models).
"""
import logging
import time
import requests
import collections
from web3 import Web3, HTTPProvider
from web3.exceptions import TransactionNotFound
from eth_account import Account
from eth_keys import keys
from bip32utils import BIP32Key

from ducatus_exchange.exchange_requests.models import ExchangeRequest
from ducatus_exchange.settings import NETWORK_SETTINGS, ROOT_KEYS, DUCX_GAS_PRICE
from ducatus_exchange.rates.models import UsdRate
from ducatus_exchange.withdrawals.utils import get_private_keys
from ducatus_exchange.consts import DECIMALS
from ducatus_exchange.bitcoin_api import BitcoinAPI, BitcoinRPC

logger = logging.getLogger('withdraw')


def withdraw_ducx_funds():

    withdraw_parameters = {
        'root_private_key': ROOT_KEYS['ducx']['private'],
        'root_public_key': ROOT_KEYS['ducx']['public'],
    }

    for key, value in withdraw_parameters.items():
        if not value:
            logger.info(f'Value not found for parameter {key}. Aborting')
            return

    all_requests = ExchangeRequest.objects.all().exclude(generated_address=None)
    for account in all_requests:
        ducx_priv_key, _ = get_private_keys(withdraw_parameters['root_private_key'], account.user.id)
        process_withdraw_ducx(withdraw_parameters, account, ducx_priv_key)

def normalize_gas_price(gas_price):
    gwei_decimals = 10 ** 9
    gas = int(round(gas_price / gwei_decimals, 0)) * gwei_decimals
    lower_gas = gas - 1 if gas > 2 else gas
    return gas, lower_gas


def process_withdraw_ducx(params, account, priv_key):
    web3_ducx = Web3(HTTPProvider(NETWORK_SETTINGS['DUCX']['endpoint']))
    gas_limit = 21000
    gas_price, fake_gas_price = normalize_gas_price(DUCX_GAS_PRICE)
    total_gas_fee = gas_price * gas_limit
    from_address = account.generated_address
    to_address = NETWORK_SETTINGS['DUCX']['address']
    balance = web3_ducx.eth.getBalance(web3_ducx.toChecksumAddress(from_address))
    nonce = web3_ducx.eth.getTransactionCount(web3_ducx.toChecksumAddress(from_address), 'pending')
    if balance < total_gas_fee:
        print(f'Address {from_address} skipped: balance {balance} < tx fee of {total_gas_fee}\n', flush=True)
        return

    withdraw_amount = int(balance) - total_gas_fee
    tx_params = {
        'chainId': web3_ducx.eth.chainId,
        'gas': gas_limit,
        'nonce': nonce,
        'gasPrice': fake_gas_price,
        'to': web3_ducx.toChecksumAddress(to_address),
        'value': int(withdraw_amount)
    }
    logger.info(f'Withdraw tx params: from {from_address} to {to_address} on amount {withdraw_amount}')
    signed_tx = Account.signTransaction(tx_params, priv_key)
    try:
        sent_tx = web3_ducx.eth.sendRawTransaction(signed_tx['rawTransaction'])
        logger.info(f'sent tx: {sent_tx.hex()}')
    except Exception as e:
        err_str = f'Refund failed for address {from_address} and amount {withdraw_amount} ({balance} - {total_gas_fee})'
        logger.error(err_str)
        logger.error(e)
    return


def withdraw_eth_funds():
    withdraw_parameters = {
        'root_private_key': ROOT_KEYS['mainnet']['private'],
        'root_public_key': ROOT_KEYS['mainnet']['public'],
        #'gas_priv_key': NETWORK_SETTINGS['ETH']['private']
    }
    for key, value in withdraw_parameters.items():
        if not value:
            logger.info(f'Value not found for parameter {key}. Aborting')
            return

    all_requests = ExchangeRequest.objects.all().exclude(eth_address=None)
    '''
    usdc_gas_transactions = collections.defaultdict(list)
    delayed_transactions_addresses = []

    print('USDC WITHDRAW (sending gas)', flush=True)
    for currency in ['USDC', 'WETH', 'WBTC']:
        for account in all_requests:
            eth_priv_key, btc_priv_key = get_private_keys(withdraw_parameters['root_private_key'], account.id)
            print(f'ETH address: {account.eth_address}', flush=True)
            try:
                process_send_gas_for_usdc(withdraw_parameters, account, eth_priv_key, usdc_gas_transactions, currency)
            except Exception as e:
                print(f'{currency} sending gas failed. Error is:', flush=True)
                print(e, flush=True)

        print(f'\n{currency} WITHDRAW (sending tokens)', flush=True)
        try:
            parse_usdc_transactions(usdc_gas_transactions, delayed_transactions_addresses, currency)
        except Exception as e:
            print(f'{currency} transaction sending failed. Error is:', flush=True)
            print(e, flush=True)

        print(f'Waiting 7 minutes because {currency} transactions affect ETH balance\n')
        time.sleep(7 * 60)
    '''
    print('ETH WITHDRAW', flush=True)
    for account in all_requests:
        eth_priv_key, _ = get_private_keys(withdraw_parameters['root_private_key'], account.user.id)
        logger.info(f'ETH address: {account.eth_address}, {Account.from_key(eth_priv_key).address}')
        '''
        if account.eth_address in delayed_transactions_addresses:
            logger.info('address {} skipped because of delayed gas transaction'.format(account.eth_address))
            continue
        '''
        try:
            process_withdraw_eth(withdraw_parameters, account, eth_priv_key)
        except Exception as e:
            print('ETH withdraw failed. Error is:', flush=True)
            print(e, flush=True)


def process_send_gas_for_usdc(params, account, priv_key, transactions, currency):
    web3 = Web3(HTTPProvider(NETWORK_SETTINGS['ETH']['endpoint']))
    myContract = web3.eth.contract(
        address=web3.toChecksumAddress(USDC_CONTRACT[currency]['address']), abi=USDC_CONTRACT[currency]['abi'])

    gas_limit = 21000
    erc20_gas_limit = 200000
    gas_price, fake_gas_price = normalize_gas_price(web3.eth.gasPrice)
    erc20_gas_price, erc20_fake_gas_price = normalize_gas_price(web3.eth.gasPrice)
    total_gas_fee = gas_price * gas_limit
    erc20_gas_fee = erc20_gas_price * erc20_gas_limit
    rate = UsdRate.objects.get(currency='ETH')
    rate = rate.rate
    token_rate = UsdRate.objects.get(currency=currency)
    token_rate = token_rate.rate
    from_address = account.eth_address
    to_address = NETWORK_SETTINGS['ETH']['address']

    balance = myContract.functions.balanceOf(web3.toChecksumAddress(from_address)).call()
    balance_check = int(((float(balance) / float(DECIMALS[currency])) * float(token_rate) / float(rate)) * float(DECIMALS['ETH']))
    ETH_balance = web3.eth.getBalance(web3.toChecksumAddress(from_address))
    nonce = web3.eth.getTransactionCount(web3.toChecksumAddress(from_address), 'pending')
    gas_nonce = web3.eth.getTransactionCount(
        web3.toChecksumAddress(NETWORK_SETTINGS['ETH']['address']), 'pending')
    if balance_check <= (total_gas_fee + erc20_gas_fee):
        logger.info(f'Address {from_address} skipped: balance {balance_check} < tx fee of {total_gas_fee + erc20_gas_fee}')
        return

    withdraw_amount = int(balance)

    tx_params = {
        'chainId': web3.eth.chainId,
        'gas': erc20_gas_limit,
        'nonce': nonce,
        'gasPrice': erc20_fake_gas_price,
        'from': web3.toChecksumAddress(from_address),
        'to': web3.toChecksumAddress(to_address),
        'value': int(withdraw_amount),
        'priv_key': priv_key
    }

    gas_tx_params = {
        'chainId': web3.eth.chainId,
        'gas': gas_limit,
        'nonce': gas_nonce,
        'gasPrice': fake_gas_price,
        'to': web3.toChecksumAddress(from_address),
        'value': int(erc20_gas_fee * 1.2)
    }

    if ETH_balance > int(erc20_gas_fee * 1.1):
        logger.info('Enough balance {} > {} for withdrawing {} from {}'.format(ETH_balance, int(erc20_gas_fee * 1.1), balance,
                                                                         from_address))
        process_withdraw_usdc([tx_params], currency)
        return

    print(f'send gas to {from_address}', flush=True)

    signed_tx = Account.signTransaction(gas_tx_params, params['gas_priv_key'])
    try:
        sent_tx = web3.eth.sendRawTransaction(signed_tx['rawTransaction'])
        print(f'sent tx: {sent_tx.hex()}', flush=True)
        transactions[sent_tx.hex()].append(tx_params)
    except Exception as e:
        err_str = f'Refund failed for address {from_address} and amount {withdraw_amount} ({balance} - {total_gas_fee})'
        print(err_str, flush=True)
        print(e, flush=True)

def parse_usdc_transactions(transactions, delayed_transactions_addresses, currency):
    count = 0
    while transactions:
        if count >= 42:
            print(
                'Transaction receipts not found in 7 minutes. Supposedly they are still in pending state due to high transaction' +
                 'traffic or they failed, please check hashs {} on Etherscan'.format(transactions.keys()),
                flush=True)
            break
        to_del = []
        for transaction in transactions.keys():
            if check_tx(transaction):
                process_withdraw_usdc(transactions[transaction], currency)
                to_del.append(transaction)
                continue
        for transaction in to_del:
            transactions.pop(transaction)
        time.sleep(10)
        count += 1
    for transaction in transactions:
        delayed_transactions_addresses.append(transactions[transaction][0]['from'].lower())


def process_withdraw_usdc(tx_params, currency):
    web3 = Web3(HTTPProvider(NETWORK_SETTINGS['ETH']['endpoint']))
    myContract = web3.eth.contract(
        address=web3.toChecksumAddress(USDC_CONTRACT[currency]['address']), abi=USDC_CONTRACT[currency]['abi'])

    priv_key = tx_params[0]['priv_key']
    from_address = tx_params[0]['from']
    to_address = tx_params[0]['to']
    value = tx_params[0]['value']
    del tx_params[0]['priv_key']
    del tx_params[0]['from']
    del tx_params[0]['to']
    del tx_params[0]['value']
    del tx_params[0]['chainId']

    print('Withdraw tx params: from {} to {} on amount {}'.format(from_address, to_address, value), flush=True)
    initial_tx = myContract.functions.transfer(to_address, value).buildTransaction(tx_params[0])
    signed_tx = Account.signTransaction(initial_tx, priv_key)
    try:
        sent_tx = web3.eth.sendRawTransaction(signed_tx['rawTransaction'])
        print(f'sent tx: {sent_tx.hex()}', flush=True)
    except Exception as e:
        err_str = 'Refund failed for address {} and amount {})'.format(from_address, value)
        print(err_str, flush=True)
        print(e, flush=True)
    return


def process_withdraw_eth(withdraw_parameters, account, priv_key):
    web3 = Web3(HTTPProvider(NETWORK_SETTINGS['ETH']['url']))
    gas_limit = 21000
    gas_price, fake_gas_price = normalize_gas_price(web3.eth.gasPrice)
    total_gas_fee = gas_price * gas_limit
    from_address = account.eth_address
    to_address = NETWORK_SETTINGS['ETH']['address']
    balance = web3.eth.getBalance(web3.toChecksumAddress(from_address))
    nonce = web3.eth.getTransactionCount(web3.toChecksumAddress(from_address), 'pending')
    if balance < total_gas_fee:
        logger.info(f'Address {from_address} skipped: balance {balance} < tx fee of {total_gas_fee}')
        return
    withdraw_amount = int(balance) - total_gas_fee
    tx_params = {
        'chainId': web3.eth.chainId,
        'gas': gas_limit,
        'nonce': nonce,
        'gasPrice': fake_gas_price,
        'to': web3.toChecksumAddress(to_address),
        'value': int(withdraw_amount)
    }
    logger.info(f'Withdraw tx params: from {from_address} to {to_address} on amount {withdraw_amount}')
    signed_tx = Account.signTransaction(tx_params, priv_key)
    try:
        sent_tx = web3.eth.sendRawTransaction(signed_tx['rawTransaction'])
        logger.info(f'sent tx: {sent_tx.hex()}')
    except Exception as e:
        err_str = f'Refund failed for address {from_address} and amount {withdraw_amount} ({balance} - {total_gas_fee})'
        logger.error(err_str)
        logger.error(e)
    return

def check_tx_success(tx):
    web3 = Web3(HTTPProvider(NETWORK_SETTINGS['ETH']['endpoint']))
    try:
        receipt = web3.eth.getTransactionReceipt(tx)
        if receipt['status'] == 1:
            return True
        else:
            return False
    except TransactionNotFound:
        return False


def check_tx(tx):
        tx_found = False

        logging.info(f'Checking transaction {tx} until found in network')
        tx_found = check_tx_success(tx)
        if tx_found:
            logging.info(f'Ok, found transaction {tx} and it was completed')
            return True


def withdraw_btc_funds():
    withdraw_parameters = {
        'root_private_key': ROOT_KEYS['mainnet']['private'],
        'root_public_key': ROOT_KEYS['mainnet']['public'],
        'address_to_btc': NETWORK_SETTINGS['BTC']['address'],
    }

    for key, value in withdraw_parameters.items():
        if not value:
            logging.info(f'Value not found for parameter {key}. Aborting')
            return

    all_requests = ExchangeRequest.objects.all().exclude(btc_address=None)
    logger.info('BTC WITHDRAW')
    for user in all_requests:
        eth_priv_key, btc_priv_key = get_private_keys(withdraw_parameters['root_private_key'], user.user.id)
        logger.info(f'BTC address: {user.btc_address}')
        try:
            process_withdraw_btc(withdraw_parameters, user, btc_priv_key)
        except Exception as e:
            logger.info('BTC withdraw failed. Error is:')
            logger.info(e)


def process_withdraw_btc(params, account, priv_key):
    if isinstance(account, str):
        from_address = account
    else:
        from_address = account.btc_address
    to_address = params['address_to_btc']
    api = BitcoinAPI()
    inputs, value, response_ok = api.get_address_unspent_all(from_address)
    if not response_ok:
        logger.info(f'Failed to fetch information about BTC address {from_address}')
        return
    balance = int(value)
    if balance <= 0:
        balance = 0
    rpc = BitcoinRPC()
    transaction_fee = rpc.relay_fee
    if balance < transaction_fee:
        logger.info(f'Address skipped: {from_address}: balance {balance} < tx fee of {transaction_fee}')
        return
    withdraw_amount = (balance - transaction_fee) / DECIMALS['BTC']
    output_params = {to_address: withdraw_amount}
    logger.info(f'Withdraw tx params: from {from_address} to {to_address} on amount {withdraw_amount}')
    logger.info(f'input_params: {inputs}')
    logger.info(f'output_params: {output_params}')
    sent_tx_hash = rpc.construct_and_send_tx(inputs, output_params, priv_key)
    if not sent_tx_hash:
        err_str = f'Withdraw failed for address {from_address} and amount {withdraw_amount} ({balance} - {transaction_fee})'
        logger.info(err_str)
    return sent_tx_hash
