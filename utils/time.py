import datetime


def now_ts():
    return int(datetime.datetime.utcnow().timestamp())
