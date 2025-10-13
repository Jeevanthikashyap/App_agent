import sys

class Logger:
    def __init__(self, filename="output.txt"):
        self.terminal = sys.stdout
        # Open the log file in 'w' (write) mode to clear it at the start of a new run
        with open(filename, "w", encoding='utf-8') as f:
            f.write("")
        self.log = open(filename, "a", encoding='utf-8') # Re-open in 'a' (append) mode

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.flush()

    def flush(self):
        # This ensures that data is written immediately to both terminal and file
        self.terminal.flush()
        self.log.flush()

    def fileno(self):
        # This makes the logger compatible with other modules that expect a file descriptor
        return self.terminal.fileno()

def setup_logger():
    """Redirects stdout to our custom logger."""
    sys.stdout = Logger()