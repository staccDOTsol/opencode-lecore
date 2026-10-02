import time

def retry(call, attempts=3, delay=0.0, sleep=time.sleep):
    """Retry an operation on transient OSError failures."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    for count in range(1, attempts + 1):
        try:
            return call()
        except OSError as error:
            if count == attempts:
                raise
            sleep(delay * (2 ** (count - 1)))
