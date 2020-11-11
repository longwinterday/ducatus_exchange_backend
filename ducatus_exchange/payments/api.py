import string
import random

import requests
from django.core.mail import send_mail
from django.db import IntegrityError

from ducatus_exchange.exchange_requests.models import ExchangeRequest
from ducatus_exchange.payments.models import Payment
from ducatus_exchange.rates.serializers import AllRatesSerializer, get_usd_prices
from ducatus_exchange.transfers.api import transfer_currency, make_ref_transfer
from ducatus_exchange.consts import DECIMALS
from ducatus_exchange.parity_interface import ParityInterfaceException
from ducatus_exchange.litecoin_rpc import DucatuscoreInterfaceException
from ducatus_exchange import settings_local
from ducatus_exchange.email_messages import voucher_html_body, warning_html_style
from ducatus_exchange.settings_local import CONFIRMATION_FROM_EMAIL
from ducatus_exchange.lottery.api import LotteryRegister


class TransferException(Exception):
    pass


def calculate_amount(original_amount, from_currency):
    to_currency = 'DUCX' if from_currency == 'DUC' else 'DUC'
    print('Calculating amount, original: {orig}, from {from_curr} to {to_curr}'.format(
        orig=original_amount,
        from_curr=from_currency,
        to_curr=to_currency
        ), flush=True
    )

    rates = AllRatesSerializer({})
    currency_rate = rates.data[to_currency][from_currency]

    if from_currency in ['ETH', 'DUCX', 'BTC', 'USDC']:
        value = original_amount * DECIMALS['DUC'] / DECIMALS[from_currency]
    elif from_currency == 'DUC':
        value = original_amount * DECIMALS[to_currency] / DECIMALS['DUC']
    else:
        value = original_amount

    print('value: {value}, rate: {rate}'.format(value=value, rate=currency_rate), flush=True)
    amount = int(value / float(currency_rate))

    return amount, currency_rate


def register_payment(request_id, tx_hash, currency, amount):
    exchange_request = ExchangeRequest.objects.get(id=request_id)

    calculated_amount, rate = calculate_amount(amount, currency)
    print('amount:', calculated_amount, 'rate:', rate,  flush=True)
    payment = Payment(
        exchange_request=exchange_request,
        tx_hash=tx_hash,
        currency=currency,
        original_amount=amount,
        rate=rate,
        sent_amount=calculated_amount
    )
    # exchange_request.from_currency = currency
    # exchange_request.save()
    print(
        'PAYMENT: {amount} {curr} ({value} DUC) on rate {rate} within request {req} with TXID: {txid}'.format(
            amount=amount,
            curr=currency,
            value=calculated_amount,
            rate=rate,
            req=exchange_request.id,
            txid=tx_hash,
        ),
        flush=True
    )

    payment.save()
    print('payment ok', flush=True)

    return payment


def parse_payment_message(message):
    tx = message.get('transactionHash')
    if not Payment.objects.filter(tx_hash=tx).count() > 0:
        request_id = message.get('exchangeId')
        amount = message.get('amount')
        currency = message.get('currency')
        print('PAYMENT:', tx, request_id, amount, currency, flush=True)
        payment = register_payment(request_id, tx, currency, amount)

        transfer_with_handle_lottery_and_referral(payment)
    else:
        print('tx {} already registered'.format(tx), flush=True)


def transfer_with_handle_lottery_and_referral(payment):
    print('starting transfer', flush=True)
    try:
        if not payment.exchange_request.user.address.startswith('voucher'):
            transfer_currency(payment)
            payment.transfer_state = 'DONE'
        elif payment.exchange_request.user.platform == 'DUC':
            usd_amount = get_usd_prices()['DUC'] * payment.sent_amount / DECIMALS['DUC']
            try:
                voucher = create_voucher(usd_amount, payment_id=payment.id)
            except IntegrityError as e:
                if 'voucher code' not in e.args[0]:
                    raise e
                voucher = create_voucher(usd_amount, payment_id=payment.id)
            send_voucher_email(voucher, payment.exchange_request.user.email, usd_amount)
            if payment.exchange_request.user.ref_address:
                make_ref_transfer(payment)
    except (ParityInterfaceException, DucatuscoreInterfaceException) as e:
        print('Transfer not completed, reverting payment', flush=True)
        payment.transfer_state = 'ERROR'
        payment.save()
        raise TransferException(e)
    print('transfer completed', flush=True)


chars_for_random = string.ascii_uppercase + string.digits


def get_random_string():
    return ''.join(random.choices(chars_for_random, k=12))


def create_voucher(usd_amount, charge_id=None, payment_id=None):
    domain = getattr(settings_local, 'VOUCHER_DOMAIN', None)
    local_voucher_url = getattr(settings_local, 'VOUCHER_LOCAL_URL', None)
    api_key = getattr(settings_local, 'VOUCHER_API_KEY', None)
    if not domain or not api_key:
        raise NameError(f'Cant create voucher for charge with {usd_amount} USD, '
                        'VOUCHER_DOMAIN and VOUCHER_API_KEY should be defined in settings_local.py')

    voucher_code = get_random_string()

    url = 'https://{}/api/v3/register_voucher/'.format(local_voucher_url)
    data = {
        "api_key": api_key,
        "voucher_code": voucher_code,
        "usd_amount": usd_amount,
        "charge_id": charge_id,
        "payment_id": payment_id,
    }
    r = requests.post(url, json=data)

    if r.status_code != 200:
        if 'voucher with this voucher code already exists' in r.content.decode():
            raise IntegrityError('voucher code')
    return r.json()


def send_voucher_email(voucher, to_email, usd_amount):
    conn = LotteryRegister.get_mail_connection()

    html_body = voucher_html_body.format(
        voucher_code=voucher['activation_code']
    )

    send_mail(
        'Your DUC Purchase Confirmation for ${}'.format(round(usd_amount, 2)),
        '',
        CONFIRMATION_FROM_EMAIL,
        [to_email],
        connection=conn,
        html_message=warning_html_style + html_body,
    )
    print('voucher message sent successfully to {}'.format(to_email), flush=True)

