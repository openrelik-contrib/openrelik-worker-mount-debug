import logging
import os
import structlog
import sys

OPENRELIK_LOG_TYPE = "OPENRELIK_LOG_TYPE"  # structlog,structlog_console,None


class Logger:
    """logger provides functionality to output plain logging, structured JSON
    logging of structured console logging.

    The logging output format is defined by setting the environment variable
    OPENRELIK_LOG_TYPE to `structlog` or `structlog_console`
    Usage:
        ```
            from openrelik_common.logging import Logger

            # Instantiate Logger class
            log = Logger()

            # Setup a logger with 2 binded key-values.
            logger = log.get_logger(name=__name__, key1=value1, key2=value2)

            # Bind additional values to the logger, they will added to any log message.
            log.bind(workflow_id=workflow_id)

            # Output debug log message.
            logger.debug(f"This is a debug message")
        ```
    """

    def __init__(self):
        if os.environ.get(OPENRELIK_LOG_TYPE, "").startswith("structlog"):
            base_processors = [
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.CallsiteParameterAdder(
                    {
                        structlog.processors.CallsiteParameter.FILENAME,
                        structlog.processors.CallsiteParameter.FUNC_NAME,
                        structlog.processors.CallsiteParameter.LINENO,
                    }
                ),
            ]

            if os.environ.get(OPENRELIK_LOG_TYPE, "") == "structlog_console":
                renderer = structlog.dev.ConsoleRenderer()
            else:
                renderer = structlog.processors.JSONRenderer()

            structlog.configure(
                processors=base_processors + [renderer],
                wrapper_class=structlog.stdlib.BoundLogger,
                logger_factory=structlog.stdlib.LoggerFactory(),
                cache_logger_on_first_use=True,
            )

            formatter = structlog.stdlib.ProcessorFormatter(
                processor=renderer,
                foreign_pre_chain=[
                    structlog.stdlib.add_log_level,
                    structlog.stdlib.add_logger_name,
                    structlog.processors.TimeStamper(fmt="iso"),
                ],
            )

            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(formatter)

            root_logger = logging.getLogger()
            for h in root_logger.handlers[:]:
                root_logger.removeHandler(h)
            root_logger.addHandler(handler)

            if root_logger.level == logging.NOTSET:
                root_logger.setLevel(logging.INFO)

    def get_logger(self, name="", wrap_logger=None, **kwargs):
        """Gets a logger instance.

        Args:
            name (str): The name of the logger.
            wrap_logger (logger): A Python logger instance that can be wrapped in a structlog instance.
            kwargs (**kwargs): Any key/value combinations to bind to the logger.

        Returns:
            logger: A (wrapped) structlog or plain python logger with key-value binded kwargs.
        """
        if wrap_logger:
            # This can be used to wrap e.g. the Celery logger in a structlog
            self.logger = structlog.wrap_logger(wrap_logger)
        elif os.environ.get(OPENRELIK_LOG_TYPE, "").startswith("structlog"):
            # Get a JSON or Console logger
            self.logger = structlog.get_logger(name)
        else:
            # Get a plain Python logger
            self.logger = logging.getLogger(name)

        # Bind any extra arguments as key-value pairs to the logger.
        self.bind(**kwargs)

        return self.logger

    def bind(self, **kwargs):
        """Bind key/values to a Logger instance.

        Args:
            kwargs (**kwargs): Any key/value combinations to bind to the logger.
        """
        if os.environ.get(OPENRELIK_LOG_TYPE, "").startswith("structlog"):
            structlog.contextvars.bind_contextvars(**kwargs)
