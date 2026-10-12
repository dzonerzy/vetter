"""What Python's standard library does, for resolve.py: each function
vetter follows, by its qualified name, and what it does (FUNCS); modules
whose every function only computes; a module's plain values. A function
not named here, from a module not named here, is one vetter doesn't
follow: asked.

What each kind does (the arguments: positional, else by keyword):

    pure      computes; its value plain data (callables given to it called)
    read      reads the path it's given (first argument)
    list      lists a folder (first argument; none: the current one)
    write     writes the path, makes or changes it (mkdir, chmod, touch)
    delete    deletes the path (rmtree: and what's under it)
    copy      reads the first, writes the second
    move      reads and deletes the first, writes the second
    link      writes the second (a link to the first)
    open      opens the path, as its mode says
    shell     runs a command line with /bin/sh
    argv      runs a command given as a list (subprocess's: a string with
              shell=True a command line)
    exec      os.exec*v / spawn*v: a program and its argument list
    execl     os.exec*l / spawn*l: a program and its arguments
    chdir     changes the current folder
    url       a request to a URL (data given: sent too)
    send      a request that sends (POST, PUT...)
    exit      ends the program
"""

FUNCS = {
    # builtins
    "builtins.open": "open",
    "builtins.exit": "exit", "builtins.quit": "exit",
    # os
    "os.remove": "delete", "os.unlink": "delete", "os.rmdir": "delete", "os.removedirs": "delete",
    "os.mkdir": "write", "os.makedirs": "write", "os.chmod": "write", "os.lchmod": "write", "os.chown": "write",
    "os.lchown": "write", "os.utime": "write", "os.truncate": "write", "os.mkfifo": "write", "os.mknod": "write",
    "os.chflags": "write", "os.lchflags": "write", "os.setxattr": "write", "os.removexattr": "write",
    "os.stat": "read", "os.lstat": "read", "os.access": "read", "os.listxattr": "read", "os.getxattr": "read",
    "os.readlink": "read", "os.statvfs": "read",
    "os.path.exists": "read", "os.path.lexists": "read", "os.path.isfile": "read", "os.path.isdir": "read",
    "os.path.islink": "read", "os.path.ismount": "read", "os.path.getsize": "read", "os.path.getmtime": "read",
    "os.path.getatime": "read", "os.path.getctime": "read", "os.path.samefile": "read",
    "os.listdir": "list", "os.scandir": "list", "os.walk": "list", "os.fwalk": "list",
    "os.rename": "move", "os.replace": "move", "os.renames": "move",
    "os.symlink": "link", "os.link": "link",
    "os.system": "shell", "os.popen": "shell",
    "os.execv": "exec", "os.execve": "exec", "os.execvp": "exec", "os.execvpe": "exec",
    "os.execl": "execl", "os.execle": "execl", "os.execlp": "execl", "os.execlpe": "execl",
    "os.spawnv": "exec", "os.spawnve": "exec", "os.spawnvp": "exec", "os.spawnvpe": "exec",
    "os.spawnl": "execl", "os.spawnle": "execl", "os.spawnlp": "execl", "os.spawnlpe": "execl",
    "os.posix_spawn": "exec", "os.posix_spawnp": "exec",
    "os.chdir": "chdir",
    "os._exit": "exit", "os.abort": "exit",
    "os.getcwdb": "pure", "os.getpid": "pure", "os.getppid": "pure", "os.getuid": "pure", "os.geteuid": "pure",
    "os.getgid": "pure", "os.getegid": "pure", "os.getgroups": "pure", "os.getlogin": "pure",
    "os.cpu_count": "pure", "os.process_cpu_count": "pure", "os.uname": "pure", "os.urandom": "pure",
    "os.get_terminal_size": "pure", "os.fspath": "pure", "os.fsencode": "pure", "os.fsdecode": "pure",
    "os.strerror": "pure", "os.isatty": "pure", "os.umask": "pure", "os.times": "pure", "os.getloadavg": "pure",
    "os.get_exec_path": "pure", "os.read": "pure", "os.write": "pure", "os.close": "pure", "os.pipe": "pure",
    "os.dup": "pure", "os.dup2": "pure", "os.get_blocking": "pure", "os.set_blocking": "pure",
    "os.waitpid": "pure", "os.wait": "pure", "os.waitstatus_to_exitcode": "pure", "os.sched_getaffinity": "pure",
    "os.path.basename": "pure", "os.path.split": "pure", "os.path.splitext": "pure", "os.path.splitdrive": "pure",
    "os.path.relpath": "pure", "os.path.commonpath": "pure", "os.path.commonprefix": "pure", "os.path.isabs": "pure",
    "os.path.normcase": "pure", "os.path.expandvars": "pure",
    "os.WEXITSTATUS": "pure", "os.WIFEXITED": "pure",
    # shutil
    "shutil.rmtree": "delete",
    "shutil.copy": "copy", "shutil.copy2": "copy", "shutil.copyfile": "copy", "shutil.copytree": "copy",
    "shutil.copymode": "copy", "shutil.copystat": "copy",
    "shutil.move": "move",
    "shutil.chown": "write",
    "shutil.disk_usage": "read",
    "shutil.which": "pure", "shutil.get_terminal_size": "pure", "shutil.copyfileobj": "pure",
    "shutil.get_archive_formats": "pure", "shutil.get_unpack_formats": "pure",
    # subprocess, pty, asyncio
    "subprocess.run": "argv", "subprocess.call": "argv", "subprocess.check_call": "argv",
    "subprocess.check_output": "argv", "subprocess.Popen": "argv",
    "subprocess.getoutput": "shell", "subprocess.getstatusoutput": "shell",
    "subprocess.CalledProcessError": "pure", "subprocess.TimeoutExpired": "pure",
    "subprocess.CompletedProcess": "pure",
    "pty.spawn": "argv",
    "asyncio.create_subprocess_exec": "execl", "asyncio.create_subprocess_shell": "shell",
    "asyncio.run": "pure", "asyncio.gather": "pure", "asyncio.sleep": "pure", "asyncio.wait_for": "pure",
    "asyncio.wait": "pure", "asyncio.TimeoutError": "pure",
    # files in other forms
    "io.open": "open", "codecs.open": "open", "gzip.open": "open", "bz2.open": "open", "lzma.open": "open",
    "io.StringIO": "pure", "io.BytesIO": "pure", "io.TextIOWrapper": "pure",
    "glob.glob": "list", "glob.iglob": "list", "glob.escape": "pure", "glob.has_magic": "pure",
    "json.load": "pure", "json.loads": "pure", "json.dump": "pure", "json.dumps": "pure",
    "json.JSONDecodeError": "pure", "json.JSONEncoder": "pure", "json.JSONDecoder": "pure",
    "tomllib.load": "pure", "tomllib.loads": "pure",
    "csv.reader": "pure", "csv.writer": "pure", "csv.DictReader": "pure", "csv.DictWriter": "pure",
    "csv.Sniffer": "pure",
    "xml.etree.ElementTree.parse": "read", "xml.etree.ElementTree.fromstring": "pure",
    "xml.etree.ElementTree.tostring": "pure", "xml.etree.ElementTree.Element": "pure",
    "xml.etree.ElementTree.SubElement": "pure",
    "configparser.ConfigParser": "pure",
    # shlex
    "shlex.split": "pure", "shlex.quote": "pure", "shlex.join": "pure",
    # sys
    "sys.exit": "exit", "sys.getsizeof": "pure", "sys.getrecursionlimit": "pure", "sys.getdefaultencoding": "pure",
    "sys.getfilesystemencoding": "pure", "sys.intern": "pure", "sys.exc_info": "pure",
    "sys.stdout.write": "pure", "sys.stderr.write": "pure", "sys.stdout.flush": "pure", "sys.stderr.flush": "pure",
    "sys.stdin.read": "pure", "sys.stdin.readline": "pure", "sys.stdin.readlines": "pure",
    "sys.stdout.buffer.write": "pure", "sys.stdin.buffer.read": "pure", "sys.stdout.reconfigure": "pure",
    "sys.stderr.reconfigure": "pure", "sys.stdin.isatty": "pure", "sys.stdout.isatty": "pure",
    # tempfile: a new file or folder in the temporary folder
    "tempfile.mkstemp": "temp", "tempfile.mkdtemp": "temp", "tempfile.NamedTemporaryFile": "temp",
    "tempfile.TemporaryFile": "temp", "tempfile.TemporaryDirectory": "temp", "tempfile.SpooledTemporaryFile": "temp",
    "tempfile.gettempdir": "pure", "tempfile.mktemp": "pure",
    # the network
    "urllib.request.urlopen": "url", "urllib.request.urlretrieve": "url", "urllib.request.Request": "request",
    "requests.get": "url", "requests.head": "url", "requests.options": "url",
    "requests.post": "send", "requests.put": "send", "requests.patch": "send", "requests.delete": "send",
    "requests.request": "send",
    "httpx.get": "url", "httpx.head": "url", "httpx.options": "url",
    "httpx.post": "send", "httpx.put": "send", "httpx.patch": "send", "httpx.delete": "send",
    "httpx.request": "send",
    "urllib.parse.urlparse": "pure", "urllib.parse.urlsplit": "pure", "urllib.parse.urlunparse": "pure",
    "urllib.parse.urlunsplit": "pure", "urllib.parse.urljoin": "pure", "urllib.parse.quote": "pure",
    "urllib.parse.quote_plus": "pure", "urllib.parse.unquote": "pure", "urllib.parse.unquote_plus": "pure",
    "urllib.parse.urlencode": "pure", "urllib.parse.parse_qs": "pure", "urllib.parse.parse_qsl": "pure",
    "urllib.error.URLError": "pure", "urllib.error.HTTPError": "pure",
    "socket.gethostname": "pure", "socket.getfqdn": "pure", "socket.socket": "socket",
    "socket.create_connection": "connect", "http.client.HTTPConnection": "host",
    "http.client.HTTPSConnection": "host",
    # things that run what they're given later: run now
    "atexit.register": "invoke",
    "threading.Thread": "thread",
    # contextlib
    "contextlib.suppress": "suppress", "contextlib.contextmanager": "identity", "contextlib.closing": "pure",
    "contextlib.redirect_stdout": "pure", "contextlib.redirect_stderr": "pure", "contextlib.nullcontext": "pure",
    "contextlib.ExitStack": "pure",
    # decorators that give back what they're given
    "functools.wraps": "decorator", "functools.lru_cache": "decorator", "functools.cache": "identity",
    "functools.total_ordering": "identity", "functools.cached_property": "identity", "typing.overload": "identity",
    "builtins.staticmethod": "identity", "builtins.classmethod": "identity", "builtins.property": "identity",
    # misc
    "platform.system": "pure", "platform.machine": "pure", "platform.release": "pure", "platform.version": "pure",
    "platform.python_version": "pure", "platform.platform": "pure", "platform.node": "pure",
    "platform.processor": "pure", "platform.python_implementation": "pure", "platform.uname": "pure",
    "platform.mac_ver": "pure", "platform.freedesktop_os_release": "read",
    "getpass.getuser": "pure", "getpass.getpass": "pure",
    "pwd.getpwnam": "pure", "pwd.getpwuid": "pure", "grp.getgrnam": "pure", "grp.getgrgid": "pure",
    "locale.getlocale": "pure", "locale.getpreferredencoding": "pure", "locale.setlocale": "pure",
    "importlib.metadata.version": "pure", "importlib.util.find_spec": "pure",
    "sysconfig.get_paths": "pure", "sysconfig.get_path": "pure", "sysconfig.get_config_var": "pure",
    "sysconfig.get_platform": "pure", "sysconfig.get_python_version": "pure",
    "site.getsitepackages": "pure", "site.getusersitepackages": "pure",
    "ast.parse": "pure", "ast.literal_eval": "pure", "ast.dump": "pure", "ast.walk": "pure", "ast.unparse": "pure",
    "ast.get_docstring": "pure", "ast.iter_child_nodes": "pure", "ast.NodeVisitor": "pure",
    "dis.dis": "pure", "tokenize.tokenize": "pure", "tokenize.generate_tokens": "pure",
    "traceback.print_exc": "pure", "traceback.format_exc": "pure", "traceback.print_exception": "pure",
    "traceback.format_exception": "pure", "warnings.warn": "pure", "warnings.filterwarnings": "pure",
    "warnings.simplefilter": "pure",
    "signal.alarm": "pure",
}

# Builtins (builtins.X) that only compute; theirs the "pure" kind
BUILTINS = {
    "print", "len", "str", "int", "float", "complex", "bool", "list", "dict", "set", "tuple", "frozenset", "sorted",
    "reversed", "enumerate", "zip", "map", "filter", "range", "min", "max", "sum", "abs", "round", "any", "all",
    "repr", "ascii", "ord", "chr", "hex", "oct", "bin", "format", "isinstance", "issubclass", "hash", "id", "iter",
    "next", "divmod", "pow", "bytes", "bytearray", "memoryview", "slice", "object", "callable", "hasattr", "input",
    "type", "aiter", "anext", "dir", "NotImplemented", "Ellipsis",
    "BaseException", "Exception", "ArithmeticError", "AssertionError", "AttributeError", "BlockingIOError",
    "BrokenPipeError", "BufferError", "ChildProcessError", "ConnectionError", "ConnectionAbortedError",
    "ConnectionRefusedError", "ConnectionResetError", "EOFError", "FileExistsError", "FileNotFoundError",
    "FloatingPointError", "GeneratorExit", "ImportError", "IndentationError", "IndexError", "InterruptedError",
    "IsADirectoryError", "KeyError", "KeyboardInterrupt", "LookupError", "MemoryError", "ModuleNotFoundError",
    "NameError", "NotADirectoryError", "NotImplementedError", "OSError", "IOError", "EnvironmentError",
    "OverflowError", "PermissionError", "ProcessLookupError", "RecursionError", "ReferenceError", "RuntimeError",
    "StopIteration", "StopAsyncIteration", "SyntaxError", "SystemError", "SystemExit", "TabError", "TimeoutError",
    "TypeError", "UnboundLocalError", "UnicodeError", "UnicodeDecodeError", "UnicodeEncodeError", "ValueError",
    "ZeroDivisionError", "Warning", "UserWarning", "DeprecationWarning", "RuntimeWarning", "ExceptionGroup",
    "BaseExceptionGroup",
}

# Builtins that never call what they're given (isinstance(x, os.PathLike))
NEVER_CALLS = {
    "builtins.print", "builtins.len", "builtins.str", "builtins.repr", "builtins.ascii", "builtins.isinstance",
    "builtins.issubclass", "builtins.type", "builtins.id", "builtins.hash", "builtins.callable", "builtins.hasattr",
    "builtins.bool", "builtins.format",
}

# Builtins whose value holds only the things in the iterables given
# (sorted(xs, key=f): xs's)
ITEMS_OF = {
    "builtins.sorted", "builtins.reversed", "builtins.list", "builtins.tuple", "builtins.set", "builtins.frozenset",
    "builtins.min", "builtins.max", "builtins.filter", "builtins.enumerate", "builtins.zip", "builtins.iter",
    "builtins.next",
}

# Modules whose every function only computes, values from values
PURE_MODULES = {
    "math", "cmath", "statistics", "string", "textwrap", "itertools", "functools", "operator", "collections",
    "collections.abc", "heapq", "bisect", "random", "secrets", "hashlib", "hmac", "base64", "binascii", "zlib",
    "struct", "uuid", "decimal", "fractions", "numbers", "unicodedata", "html", "difflib", "pprint", "enum",
    "typing", "copy", "calendar", "colorsys", "ipaddress", "keyword", "errno", "stat", "re", "time", "datetime",
    "zoneinfo", "fnmatch", "array", "dataclasses", "abc", "types", "reprlib", "weakref", "queue", "graphlib",
    "string.templatelib", "json.decoder", "json.encoder", "shlex", "posixpath", "ntpath", "textwrap", "gettext",
    "mimetypes", "email", "email.utils", "email.message", "quopri", "codecs", "contextvars",
}

# Functions of the pure modules that don't only compute (types.FunctionType
# makes a function from code; codecs.open: open's)
NOT_PURE = {
    "types.FunctionType", "types.LambdaType", "types.CodeType", "types.MethodType", "types.ModuleType",
    "codecs.open", "codecs.register", "mimetypes.init", "mimetypes.read_mime_types", "gettext.install",
    "gettext.translation", "dataclasses.dataclass", "dataclasses.make_dataclass", "enum.Enum", "abc.ABC",
    "abc.ABCMeta", "typing.NamedTuple", "typing.TypedDict", "typing.Protocol", "weakref.finalize",
    "collections.namedtuple", "operator.methodcaller", "operator.attrgetter",
    # (may run ifconfig, ip: programs found on PATH)
    "uuid.uuid1", "uuid.getnode",
}

# The classes of pure modules whose methods are pure too
# (datetime.datetime.now; a pure module's other names reached through it,
# shlex.os.system, aren't)
PURE_CLASSES = {
    "datetime.datetime", "datetime.date", "datetime.time", "datetime.timedelta", "datetime.timezone",
    "decimal.Decimal", "fractions.Fraction", "string.Template", "string.Formatter", "collections.OrderedDict",
    "collections.Counter", "collections.defaultdict", "collections.deque", "collections.ChainMap", "re.Pattern",
    "ipaddress.ip_address", "ipaddress.IPv4Address", "ipaddress.IPv6Address", "ipaddress.ip_network",
    "enum.Enum", "random.Random", "array.array", "types.SimpleNamespace", "zoneinfo.ZoneInfo",
}

# Modules that are packages of others (from os import path: a module)
MODULES = {
    "os", "os.path", "sys", "subprocess", "shutil", "pathlib", "json", "re", "glob", "shlex", "io", "tempfile",
    "time", "datetime", "math", "cmath", "random", "string", "textwrap", "collections", "collections.abc",
    "itertools", "functools", "hashlib", "base64", "platform", "urllib", "urllib.parse", "urllib.request",
    "urllib.error", "http", "http.client", "socket", "csv", "typing", "dataclasses", "enum", "uuid", "struct",
    "binascii", "operator", "statistics", "difflib", "pprint", "fnmatch", "stat", "errno", "zlib", "gzip", "bz2",
    "lzma", "codecs", "unicodedata", "html", "xml", "xml.etree", "xml.etree.ElementTree", "traceback", "warnings",
    "asyncio", "pty", "atexit", "threading", "contextlib", "getpass", "pwd", "grp", "locale", "importlib",
    "importlib.metadata", "importlib.util", "sysconfig", "site", "ast", "dis", "tokenize", "signal", "tomllib",
    "configparser", "requests", "httpx", "heapq", "bisect", "secrets", "hmac", "decimal", "fractions",
    "numbers", "copy", "calendar", "colorsys", "ipaddress", "keyword", "zoneinfo", "array", "abc", "types",
    "reprlib", "weakref", "queue", "graphlib", "posixpath", "ntpath", "gettext", "mimetypes", "email",
    "email.utils", "email.message", "quopri", "contextvars", "inspect", "json.decoder", "json.encoder",
}

# Values of modules that are plain data (and constants known)
CONSTS = {
    "os.sep": "/", "os.altsep": None, "os.extsep": ".", "os.pathsep": ":", "os.linesep": "\n", "os.curdir": ".",
    "os.pardir": "..", "os.devnull": "/dev/null", "os.name": "posix", "os.path.sep": "/", "os.path.curdir": ".",
    "os.path.pardir": "..", "os.path.extsep": ".", "os.path.pathsep": ":", "os.path.devnull": "/dev/null",
}
DATA_ATTRS = {
    "sys.version", "sys.version_info", "sys.platform", "sys.maxsize", "sys.byteorder", "sys.executable",
    "sys.prefix", "sys.base_prefix", "sys.exec_prefix", "sys.implementation", "sys.flags", "sys.float_info",
    "sys.hexversion", "sys.api_version", "sys.copyright", "sys.stdin", "sys.stdout", "sys.stderr",
    "sys.stdin.buffer", "sys.stdout.buffer", "sys.stderr.buffer", "sys.builtin_module_names",
    "sys.stdlib_module_names", "sys.orig_argv", "sys.maxunicode",
    "subprocess.PIPE", "subprocess.DEVNULL", "subprocess.STDOUT",
    "os.O_RDONLY", "os.O_WRONLY", "os.O_RDWR", "os.O_CREAT", "os.O_EXCL", "os.O_TRUNC", "os.O_APPEND",
    "os.F_OK", "os.R_OK", "os.W_OK", "os.X_OK", "os.P_WAIT", "os.P_NOWAIT", "os.EX_OK",
    "signal.SIGTERM", "signal.SIGKILL", "signal.SIGINT", "signal.SIGHUP", "signal.SIGALRM",
    "socket.AF_INET", "socket.AF_INET6", "socket.AF_UNIX", "socket.SOCK_STREAM", "socket.SOCK_DGRAM",
}

# Methods of plain data: str, bytes, numbers, list, dict, set, tuple, and
# what the pure modules give (a match, a date, a hash, a parsed URL, a
# finished process): none acts on anything but the value
DATA_METHODS = {
    "strip", "lstrip", "rstrip", "split", "rsplit", "splitlines", "join", "replace", "lower", "upper", "title",
    "capitalize", "casefold", "swapcase", "startswith", "endswith", "find", "rfind", "index", "rindex", "count",
    "format", "format_map", "encode", "decode", "isdigit", "isdecimal", "isnumeric", "isalpha", "isalnum",
    "isspace", "isupper", "islower", "istitle", "isidentifier", "isprintable", "isascii", "partition",
    "rpartition", "center", "ljust", "rjust", "zfill", "expandtabs", "translate", "maketrans", "removeprefix",
    "removesuffix", "hex", "fromhex", "bit_length", "bit_count", "to_bytes", "from_bytes", "is_integer",
    "as_integer_ratio", "conjugate", "real", "imag",
    "get", "keys", "values", "items", "copy", "append", "extend", "insert", "pop", "popitem", "remove", "clear",
    "update", "setdefault", "sort", "reverse", "add", "discard", "union", "intersection", "difference",
    "symmetric_difference", "issubset", "issuperset", "isdisjoint", "intersection_update", "difference_update",
    "symmetric_difference_update", "appendleft", "popleft", "extendleft", "rotate", "most_common", "elements",
    "subtract", "total", "fromkeys", "move_to_end",
    "group", "groups", "groupdict", "start", "end", "span", "match", "search", "fullmatch", "findall", "finditer",
    "sub", "subn", "expand", "pattern", "flags", "lastindex", "lastgroup", "string",
    "strftime", "isoformat", "timestamp", "date", "time", "weekday", "isoweekday", "isocalendar", "timetuple",
    "utctimetuple", "astimezone", "total_seconds", "toordinal", "ctime", "utcoffset", "tzname", "dst",
    "hexdigest", "digest", "geturl", "_replace", "_asdict", "returncode", "stdout", "stderr", "args",
    "check_returncode", "communicate", "wait", "poll", "pid",
    "read", "readline", "readlines", "write", "writelines", "flush", "getvalue", "seek", "tell", "close",
    "fileno", "isatty", "readable", "writable", "seekable", "buffer", "truncate",
    "writerow", "writerows", "writeheader", "fieldnames", "line_num", "dialect",
    "getroot", "findtext", "iter", "itertext", "attrib", "tag", "text", "tail", "set",
    "sections", "has_section", "options", "has_option", "getint", "getfloat", "getboolean", "read_string",
    "read_dict", "add_section",
    "scheme", "netloc", "path", "params", "query", "fragment", "hostname", "port", "username", "password",
    "substitute", "safe_substitute", "dumps", "lineno", "col_offset", "body", "name", "names", "id", "value",
    "attr", "func", "keywords", "targets", "elts", "ctx", "visit", "generic_visit",
    "is_alive", "daemon", "ident",
    "major", "minor", "micro", "releaselevel", "serial", "year", "month", "day", "hour", "minute", "second",
    "microsecond", "days", "seconds", "microseconds", "tzinfo", "st_size", "st_mtime", "st_mode", "st_uid",
    "st_gid", "st_atime", "st_ctime", "st_ino", "st_nlink", "sysname", "nodename", "release", "version", "machine",
    "errno", "strerror", "filename", "code", "reason", "headers", "status", "msg", "output", "cmd",
}

# Path's methods (and properties) and what they do
PATH_METHODS = {
    "joinpath": "path", "with_name": "path", "with_suffix": "path", "with_stem": "path", "relative_to": "path",
    "parent": "path", "absolute": "path", "resolve": "path", "expanduser": "path",
    "name": "data", "stem": "data", "suffix": "data", "suffixes": "data", "parts": "data", "parents": "data",
    "anchor": "data", "drive": "data", "root": "data", "is_absolute": "data", "as_posix": "data", "match": "data",
    "full_match": "data", "is_relative_to": "data", "as_uri": "data", "is_reserved": "data",
    "exists": "read", "is_file": "read", "is_dir": "read", "is_symlink": "read", "is_mount": "read",
    "is_socket": "read", "is_fifo": "read", "is_block_device": "read", "is_char_device": "read", "stat": "read",
    "lstat": "read", "owner": "read", "group": "read", "read_text": "read", "read_bytes": "read",
    "samefile": "read", "readlink": "read", "is_junction": "read",
    "iterdir": "list", "glob": "list", "rglob": "list", "walk": "list",
    "write_text": "write", "write_bytes": "write", "touch": "write", "mkdir": "write", "chmod": "write",
    "lchmod": "write", "symlink_to": "write", "hardlink_to": "write",
    "unlink": "delete", "rmdir": "delete",
    "rename": "move", "replace": "move", "move": "move", "move_into": "move",
    "copy": "copy", "copy_into": "copy",
    "open": "open",
}

# Modules that do something when imported
IMPORT_EFFECTS = {"antigravity": "opens a web browser", "this": "", "__hello__": "", "__phello__": ""}

# Modules Python has imported when it starts, before the current folder
# is on its path: never the folder's own files
PRELOADED = {
    "sys", "builtins", "os", "os.path", "posixpath", "stat", "genericpath", "abc", "codecs", "io", "encodings",
    "site", "marshal", "posix", "time", "_io", "_thread", "_weakref", "_warnings", "_imp", "_abc", "_stat",
    "_codecs", "_signal", "_sitebuiltins", "_collections_abc", "_frozen_importlib", "_frozen_importlib_external",
    "zipimport",
}

STDLIB = {
    "__future__", "_thread", "abc", "aifc", "argparse", "array", "ast", "asyncio", "atexit", "audioop", "base64",
    "bdb", "binascii", "bisect", "builtins", "bz2", "cProfile", "calendar", "cgi", "cgitb", "chunk", "cmath",
    "cmd", "code", "codecs", "codeop", "collections", "colorsys", "compileall", "concurrent", "configparser",
    "contextlib", "contextvars", "copy", "copyreg", "crypt", "csv", "ctypes", "curses", "dataclasses",
    "datetime", "dbm", "decimal", "difflib", "dis", "doctest", "email", "encodings", "ensurepip", "enum",
    "errno", "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch", "fractions", "ftplib", "functools",
    "gc", "genericpath", "getopt", "getpass", "gettext", "glob", "graphlib", "grp", "gzip", "hashlib", "heapq",
    "hmac", "html", "http", "idlelib", "imaplib", "imghdr", "importlib", "inspect", "io", "ipaddress",
    "itertools", "json", "keyword", "lib2to3", "linecache", "locale", "logging", "lzma", "mailbox", "mailcap",
    "marshal", "math", "mimetypes", "mmap", "modulefinder", "multiprocessing", "netrc", "nis", "nntplib",
    "ntpath", "nturl2path", "numbers", "opcode", "operator", "optparse", "os", "ossaudiodev", "pathlib", "pdb",
    "pickle", "pickletools", "pipes", "pkgutil", "platform", "plistlib", "poplib", "posix", "posixpath",
    "pprint", "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc", "pydoc_data", "pyexpat",
    "queue", "quopri", "random", "re", "readline", "reprlib", "resource", "rlcompleter", "runpy", "sched",
    "secrets", "select", "selectors", "shelve", "shlex", "shutil", "signal", "site", "smtplib", "sndhdr",
    "socket", "socketserver", "spwd", "sqlite3", "sre_compile", "sre_constants", "sre_parse", "ssl", "stat",
    "statistics", "string", "stringprep", "struct", "subprocess", "sunau", "symtable", "sys", "sysconfig",
    "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile", "termios", "textwrap", "this", "threading",
    "time", "timeit", "tkinter", "token", "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty",
    "turtle", "turtledemo", "types", "typing", "unicodedata", "unittest", "urllib", "uu", "uuid", "venv",
    "warnings", "wave", "weakref", "webbrowser", "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile",
    "zipimport", "zlib", "zoneinfo", "antigravity", "annotationlib", "compression",
}

# Installed packages vetter follows (the network's)
FOLLOWED_PACKAGES = {"requests", "httpx"}
