import celery
from celery.schedules import crontab
import os
import logging
from dateutil import tz
eastern = tz.gettz('Europe/Moscow')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ducatus_exchange.settings')
import django
django.setup()

from ducatus_exchange.exchange_requests.task_services import update_duc_and_ducx_balances
from ducatus_exchange.exchange_requests.utils import dayly_reset, weekly_reset
from ducatus_exchange.payments.task_services import send_duc_on_queue
from ducatus_exchange.stats.mongo_checker import get_duc_balances
from ducatus_exchange.stats.api import update_nodes
from ducatus_exchange.settings import RABBITMQ_URL

logger = logging.getLogger('task')

app = celery.Celery('task', broker=RABBITMQ_URL)


@app.task
def reset_dayly():
    logger.info(msg='Starting dayly reset')
    dayly_reset()
    logger.info(msg='dayly reset complete')


@app.task
def reset_weekly():
    logger.info(msg='Starting weekly reset')
    weekly_reset()
    logger.info(msg='weekly reset complete')


@app.task
def update_duc_balances():
    logger.info(msg='Starting DUC balance updating')
    get_duc_balances()
    logger.info(msg='DUC balance updating complete')


@app.task
def update_ducx_node_balandes():
    logger.info(msg='Starting DUCX node balance updating')
    update_nodes()
    logger.info(msg='DUC node balance updating complete')


@app.task
def send_duc_queue():
    logger.info(msg='Starting DUC send queue task')
    send_duc_on_queue()


@app.task
def update_duc_and_ducx_balance():
    logger.info(msg='Starting update DUC and DUCX wallet balance task')
    update_duc_and_ducx_balances()



app.conf.beat_schedule = {
    'dayly_task': {
        'task': 'task.reset_dayly',
        'schedule': crontab(hour=0, minute=0),
    },
    'weekly_task': {
        'task': 'task.reset_weekly',
        'schedule': crontab(day_of_week=0, hour=0, minute=0),
    },
    'update_duc': {
        'task': 'task.update_duc_balances',
        'schedule': crontab(hour=12, minute=0),
    },
    'update_ducx_nodes': {
        'task': 'task.update_ducx_node_balandes',
        'schedule': crontab(minute=0),
    },
    'send_duc_queue': {
        'task': 'task.send_duc_queue',
        'schedule': crontab(minute='*'),
    },
    'update_duc_and_ducx_balance': {
        'task': 'task.update_duc_and_ducx_balance',
        'schedule': crontab(minute='*'),
    }
}
