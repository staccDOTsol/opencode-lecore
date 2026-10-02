import time

def retry(call, attempts=3, delay=0.0, sleep=time.sleep):
    """Retry an operation on transient OSError failures."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    current_delay = delay
    for _ in range(attempts):
        try:
            return call()
        except OSError:
            last_attempt = _ + 1 >= attempts
            if last_attempt:
                raise
            sleep(current_delay)
            current_delay *= 2
    return call()
