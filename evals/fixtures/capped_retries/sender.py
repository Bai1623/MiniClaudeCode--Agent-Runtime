"""Message delivery with retry support."""


def send_with_retry(send, sleep, retries: int = 3, base: int = 1, cap: int = 30):
    try:
        return send()
    except RuntimeError:
        sleep(base)
        return send()
