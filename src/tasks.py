from openrelik_worker_common.task_utils import create_task_result, get_input_files
from openrelik_worker_common.logging import Logger
from openrelik_worker_common.mount_utils import BlockDevice
from openrelik_worker_common.file_utils import create_output_file

from celery import signals
from .app import celery
from subprocess import Popen, PIPE

import glob
import pprint

log = Logger()
logger = log.get_logger(__name__)

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
    log.bind(task_id=task_id, task_name=task.name, worker_name=TASK_METADATA.get("display_name"))


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
    log.bind(workflow_id=workflow_id)
    logger.info(f"Starting {TASK_NAME}")

    input_files = get_input_files(pipe_result, input_files or [])
    output_files = []

    for input_file in input_files:
        output_file = create_output_file(
            output_path,
            display_name=f"debug-{input_file.get('display_name')}",
            extension=".txt",
        )
        debug_output = "openrelik-worker-mount-debug output:\n\n"
        debug_output += f"Processing {input_file.get('display_name')} in path {input_file.get('path')}\n\n"
        try:
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
