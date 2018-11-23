import re
import socket


def net_check(port, addr=None):
    """Checks the availablility of a port"""
    port = int(port)
    try:
        addr = socket.gethostbyname(addr)

        # Then try to connect to the port
        try:
            socket.create_connection((addr, port), timeout=10)
            return True
        except socket.error:
            return False
    except Exception as e:
        print(e)
        return False


def process_pytest_path(path):
    # Processes the path elements with regards to []
    path = path.lstrip("/")
    if len(path) == 0:
        return []
    try:
        seg_end = path.index("/")
    except ValueError:
        seg_end = None
    try:
        param_start = path.index("[")
    except ValueError:
        param_start = None
    try:
        param_end = path.index("]")
    except ValueError:
        param_end = None
    if seg_end is None:
        # Definitely a final segment
        return [path]
    else:
        if (
            param_start is not None
            and param_end is not None
            and seg_end > param_start
            and seg_end < param_end
        ):
            # The / inside []
            segment = path[: param_end + 1]
            rest = path[param_end + 1 :]
            return [segment] + process_pytest_path(rest)
        else:
            # The / that is not inside []
            segment = path[:seg_end]
            rest = path[seg_end + 1 :]
            return [segment] + process_pytest_path(rest)


def safe_string(o):
    """This will make string out of ANYTHING without having to worry about the stupid Unicode errors

    This function tries to make str/unicode out of ``o`` unless it already is one of those and then
    it processes it so in the end there is a harmless ascii string.

    Args:
        o: Anything.
    """
    if not isinstance(o, str):
        o = str(o)
    if isinstance(o, bytes):
        o = o.decode("utf-8", "ignore")
    o = o.encode("ascii", "xmlcharrefreplace").decode("ascii")
    return o


def _prenormalize_text(text):
    """Makes the text lowercase and removes all characters that are not digits, alphas, or spaces"""
    # _'s represent spaces so convert those to spaces too
    return re.sub(r"[^a-z0-9 ]", "", text.strip().lower().replace("_", " "))


def _replace_spaces_with(text, delim):
    """Contracts spaces into one character and replaces it with a custom character."""
    return re.sub(r"\s+", delim, text)


def normalize_text(text):
    """Converts a string to a lowercase string containing only letters, digits and spaces.

    The space is always one character long if it is present.
    """
    return _replace_spaces_with(_prenormalize_text(text), " ")


def _random_port(tcp=True):
    """Get a random port number for making a socket

    Args:
        tcp: Return a TCP port number if True, UDP if False

    This may not be reliable at all due to an inherent race condition. This works
    by creating a socket on an ephemeral port, inspecting it to see what port was used,
    closing it, and returning that port number. In the time between closing the socket
    and opening a new one, it's possible for the OS to reopen that port for another purpose.

    In practical testing, this race condition did not result in a failure to (re)open the
    returned port number, making this solution squarely "good enough for now".
    """
    # Port 0 will allocate an ephemeral port
    socktype = socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM
    s = socket.socket(socket.AF_INET, socktype)
    s.bind(("", 0))
    addr, port = s.getsockname()
    s.close()
    return port
