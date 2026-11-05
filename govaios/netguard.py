import socket

_ORIG_INIT = socket.socket.__init__
_ORIG_GETADDRINFO = socket.getaddrinfo
_installed = False
_BLOCKED = "network blocked during run"


# shortcut: in-process guard only; a C extension can bypass it. Runs under test use a credential-free GOVAIOS_HOME, so a bypass leaks nothing. The OS-level egress block (sandbox profile) comes with plan 2.
def block_all_network() -> None:
    global _installed
    if _installed:
        return
    _installed = True

    def guarded_init(self, family=-1, type=-1, proto=-1, fileno=None):
        # family -1 is the socket module's default, which is AF_INET
        if family in (-1, socket.AF_INET, socket.AF_INET6):
            raise PermissionError(_BLOCKED)
        _ORIG_INIT(self, family, type, proto, fileno)

    def guarded_getaddrinfo(*args, **kwargs):
        raise PermissionError(_BLOCKED)

    socket.socket.__init__ = guarded_init
    socket.getaddrinfo = guarded_getaddrinfo
