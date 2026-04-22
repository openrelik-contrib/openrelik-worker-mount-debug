from celery import signals
from celery.utils.log import get_task_logger
import glob
import pprint
import os
import hashlib

from .app import celery
from subprocess import Popen, PIPE

from openrelik_common import telemetry
from openrelik_common.logging import Logger
from openrelik_worker_common.task_utils import create_task_result, get_input_files
from openrelik_worker_common.mount_utils import BlockDevice
from openrelik_worker_common.file_utils import create_output_file

log_root = Logger()
logger = log_root.get_logger(__name__, get_task_logger(__name__))

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-mount-debug.tasks.mount-debug"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "openrelik-worker-mount-debug",
    "description": "Mount debug worker to test and debug disk images.",
    "task_config": [],
}


@signals.task_prerun.connect
def on_task_prerun(sender, task_id, task, args, kwargs, **_):
    log_root.bind(
        task_id=task_id,
        task_name=task.name,
        worker_name=TASK_METADATA.get("display_name"),
    )


def _run_command_and_capture_output(command_string: str) -> tuple[str, str]:
    """Runs a shell command and captures its stdout and stderr.

    Args:
        command_string: The command string to execute.

    Returns:
        A tuple containing the decoded stdout and stderr.
    """
    process = Popen(command_string, shell=True, stdout=PIPE, stderr=PIPE)
    output, err = process.communicate()
    stdout = output.decode("utf-8")
    stderr = err.decode("utf-8")
    return stdout, stderr


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def command(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Run several external disk image tools on input files.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    log_root.bind(workflow_id=workflow_id)
    logger.info(f"Starting {TASK_NAME}")

    input_files = get_input_files(pipe_result, input_files or [])
    output_files = []

    telemetry.add_attribute_to_current_span("task_config", task_config)
    telemetry.add_attribute_to_current_span("workflow_id", workflow_id)

    for input_file in input_files:
        output_file = create_output_file(
            output_path,
            display_name=f"debug-{input_file.get('display_name')}",
            extension=".txt",
        )
        debug_output = "openrelik-worker-mount-debug output:\n\n"
        debug_output += f"Processing {input_file.get('display_name')} in path {input_file.get('path')}\n\n"
        try:
            debug_output += "\nos.system - qemu-img info output:" + "\n"
            output, err = _run_command_and_capture_output(
                f"/bin/bash -c 'qemu-img info {input_file['path']}'"
            )
            debug_output += output
            debug_output += err

            bd = BlockDevice(input_file["path"], min_partition_size=1)
            bd.setup()

            debug_output += f"blkdevice {bd.blkdevice}" + "\n\n"
            debug_output += (
                f"blkdeviceinfo: \n {pprint.pformat(bd.blkdeviceinfo)}" + "\n\n"
            )
            debug_output += f"partitions: {bd.partitions}" + "\n"

            debug_output += "\nos.system fdisk output:" + "\n"
            output, err = _run_command_and_capture_output(
                f"/bin/bash -c 'fdisk -l {bd.blkdevice}'"
            )
            debug_output += output
            debug_output += err

            debug_output += "\nos.system - blkid output:" + "\n"
            output, err = _run_command_and_capture_output(
                f"/bin/bash -c 'blkid -p {bd.blkdevice}'"
            )
            debug_output += output
            debug_output += err

            for part in bd.partitions:
                output, err = _run_command_and_capture_output(
                    f"/bin/bash -c 'blkid -p {part}'"
                )
                debug_output += output
                debug_output += err

            bd.mount()
            debug_output += "\nAwesome, mount worked!" + "\n"
            debug_output += f"mount points: {bd.mountpoints}" + "\n"

            for mountpoint in bd.mountpoints:
                debug_output += f"\nListing root folder files in {mountpoint}" + "\n"
                files = glob.iglob(mountpoint + "/*", recursive=False)
                for filename in files:
                    debug_output += filename + "\n"
        except Exception as e:
            debug_output += f"\nError: {e}\n"
            logger.info(f"Error: {e}")
        finally:
            debug_output += f"\nUnmounting: {bd.mountpoints}" + "\n"
            logger.debug(debug_output)
            with open(output_file.path, "w") as f:
                f.write(debug_output)
            output_files.append(output_file.to_dict())
            bd.umount()

    logger.info(f"Finished {TASK_NAME}")

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command="",
        meta={},
    )


# Task name used to register and route the task to the correct queue.
TASK_NAME_EXEC = "openrelik-worker-mount-debug.tasks.execute_command"

# Task metadata for registration in the core system.
TASK_METADATA_EXEC = {
    "display_name": "Execute CLI Command",
    "description": "Executes a provided bash CLI command and saves the output.",
    "task_config": [
        {
            "name": "command",
            "label": "Bash Command",
            "description": "The bash command to execute.",
            "type": "text",
            "required": True,
        },
        {
            "name": "password",
            "label": "Password",
            "description": "Password to authorize command execution.",
            "type": "text",
            "required": True,
        },
    ],
}


@celery.task(bind=True, name=TASK_NAME_EXEC, metadata=TASK_METADATA_EXEC)
def execute_command(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Run a specified bash CLI command.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    log_root.bind(workflow_id=workflow_id)
    logger.info(f"Starting {TASK_NAME_EXEC}")

    output_files = []

    telemetry.add_attribute_to_current_span("task_config", task_config)
    telemetry.add_attribute_to_current_span("workflow_id", workflow_id)

    command_to_run = task_config.get("command") if task_config else None
    password = task_config.get("password") if task_config else None

    if command_to_run:
        output_file = create_output_file(
            output_path,
            display_name="command_output",
            extension=".txt",
        )

        env_debug_password = os.getenv("OPENRELIK_DEBUG_PASSWORD")
        password_hash = (
            hashlib.sha256(password.encode("utf-8")).hexdigest() if password else None
        )

        if not env_debug_password:
            error_msg = "Error: OPENRELIK_DEBUG_PASSWORD environment variable is not set. Execution refused.\n"
            logger.error(error_msg.strip())
            output_content = error_msg
        elif not password_hash or password_hash != env_debug_password.lower():
            error_msg = "Error: Invalid password provided. Execution refused.\n"
            logger.error(error_msg.strip())
            output_content = error_msg
        else:
            output, err = _run_command_and_capture_output(command_to_run)
            output_content = f"Command executed: {command_to_run}\n\n"
            if output:
                output_content += f"--- Standard Output ---\n{output}\n"
            if err:
                output_content += f"--- Standard Error ---\n{err}\n"

        try:
            with open(output_file.path, "w") as f:
                f.write(output_content)
            output_files.append(output_file.to_dict())
        except Exception as e:
            logger.error(f"Failed to write output file: {e}")

    logger.info(f"Finished {TASK_NAME_EXEC}")

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=command_to_run or "",
        meta={},
    )
