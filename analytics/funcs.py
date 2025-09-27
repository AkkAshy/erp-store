from datetime import datetime, timedelta

def get_date_range(date_from, date_to):
    start = datetime.strptime(date_from, "%Y-%m-%d")
    end = datetime.strptime(date_to, "%Y-%m-%d")

    result = []
    current = start
    while current <= end:
        result.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return result


def get_month_range(date_from, date_to):
    start = datetime.strptime(date_from, "%Y-%m-%d")
    end = datetime.strptime(date_to, "%Y-%m-%d")

    result = []
    current = start
    while current <= end:
        result.append(current.strftime("%Y-%m"))
        current += timedelta(days=1)
    return result


