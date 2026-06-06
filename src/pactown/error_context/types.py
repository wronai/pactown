from dataclasses import dataclass

MAX_6 = 6
MAX_250 = 250
MAX_12000 = 12000
MAX_20000 = 20000


@dataclass
class ErrorContextConfig:
    max_log_lines: int = MAX_250
    max_log_chars: int = MAX_12000
    max_stderr_chars: int = MAX_12000
    max_files: int = MAX_6
    max_file_bytes: int = MAX_20000
