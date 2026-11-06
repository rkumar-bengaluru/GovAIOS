import socket

_ORIG_INIT = socket.socket.__init__
_ORIG_GETADDRINFO = socket.getaddrinfo
_installed = False
_BLOCKED = "network blocked during run"


# shortcut: in-process guard only; a C extension can bypass it. Runs under test use a credential-free GOVAIOS_HOME, so a bypass leaks nothing. Second layer (clear errors, covers the dev path); the OS-level egress block is the sandbox profile, decision row 22.
def block_all_network() -> None:
    global _installed
    if _installed:
        return
    _installed = True

    def guarded_init(self, family=-1, type=-1, proto=-1, fileno=None):
        # allowlist, not blocklist: only AF_UNIX (family -1 defaults to AF_INET, so it is blocked too)
        if family != socket.AF_UNIX:
            raise PermissionError(_BLOCKED)
        _ORIG_INIT(self, family, type, proto, fileno)

    def guarded_getaddrinfo(*args, **kwargs):
        raise PermissionError(_BLOCKED)

    socket.socket.__init__ = guarded_init
    # name lookups leak the hostname via DNS even with no socket of ours
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
        setattr(socket, name, guarded_getaddrinfo)
