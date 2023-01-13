#!/usr/bin/env python3

import time
import subprocess
import smtplib
import ssl
import random
from pathlib import Path
import os

#
# Backup config
#

# Subdirectories of home dir to backup
BACKUP_DIRS = [
    "Documents",
    "Pictures",
    "Music",
    "Videos",
    "build",
    "AppData/Roaming",
    "VirtualBox VMs",
]

RESTIC_ENV_VARS = {
    # Restic repository location.
    # Here we're using a B2 bucket with the S3-compatible endpoint as
    # recommended over the B2 backend in the documentation
    "RESTIC_REPOSITORY": "s3:s3.us-east-005.backblazeb2.com/MYBUCKETNAME",
    # From B2 application key
    "AWS_ACCESS_KEY_ID": "*************",
    "AWS_SECRET_ACCESS_KEY": "*********************",
    # For Restic's encryption
    "RESTIC_PASSWORD": "*************************",
}

# Send email on success/error
EMAIL_ADDRESS = "me@example.com"
EMAIL_PASSWORD = "*******************"

# Don't back up paths that match these patterns
EXCLUDE_PATH_PATTERNS = [
    "node_modules/**",
    ".cache/**",
    ".vscode/**",
    ".npm/**",
    ".vscode-server/**",
]

#
# End backup config
#


def gen_exclude_flags(patterns: list[str]):
    flags = []
    for pattern in patterns:
        flags.append("--exclude")
        flags.append(pattern)
    return flags


# Restic flags common to Windows and WSL
RESTIC_DEFAULT_ARGS = gen_exclude_flags(EXCLUDE_PATH_PATTERNS)

RCLONE_DEST_PATH = Path.home() / "backup"
RCLONE_BASE = [
    "rclone",
    "sync",
    "--links",
] + gen_exclude_flags(EXCLUDE_PATH_PATTERNS)


class ShellError(Exception):
    def __init__(self, msg):
        self.msg = msg


def sh(cmd: list[str], check=True, stdin_str=None, env=None):
    print(f"Running command: {cmd}")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    stdout, stderr = proc.communicate(stdin_str)
    stdout = stdout.strip()
    stderr = stderr.strip()
    if check and proc.returncode != 0:
        msg = (
            f"[script] Failed to run command: {proc.args}\n"
            f"[script] Return code: {proc.returncode}\n\n"
            f"[script] Stdout:\n{stdout}\n"
            f"[script] Stderr:\n{stderr}"
        )
        print(msg)
        raise ShellError(msg)
    if len(stdout) > 0 or len(stderr) > 0:
        print(f"[script] Stdout:\n{stdout}\n[script] Stderr:\n{stderr}")
    return stdout


def notify(subject, msg):
    port = 465  # For SSL

    # Create a secure SSL context
    context = ssl.create_default_context()

    with smtplib.SMTP_SSL("smtp.gmail.com", port, context=context) as server:
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        message = f"Subject: {subject}\n\n{msg}"

        server.sendmail(EMAIL_ADDRESS, EMAIL_ADDRESS, message)


def try_task(task_func, error_list):
    try:
        task_func()
    except ShellError as e:
        error_list.append(e.msg)
    except Exception as e:
        error_list.append(e)


def backup_windows_dir(dir: Path):
    print(f"Snapshotting dir with restic: {dir}")
    cmd = (
        ["restic"]
        + RESTIC_DEFAULT_ARGS
        + ["backup", str(dir), "--use-fs-snapshot", "--tag", "Windows"]
    )
    env = os.environ.copy()
    for var, val in RESTIC_ENV_VARS.items():
        env[var] = val
    sh(cmd, env=env)
    print(f"Finished snapshotting dir with restic: {dir}")


def backup_aws():
    ghidra_src = "ghidra:/home/ghidra"
    ghidra_dst = RCLONE_DEST_PATH / "aws" / "ghidra"
    ghidra_cmd = RCLONE_BASE + [
        str(ghidra_src),
        str(ghidra_dst),
        "--exclude",
        ".dotfiles/**",
    ]
    sh(ghidra_cmd)
    print("Downloaded Ghidra community server repository")

    twitchbot_src = "twitchbot:/home/twitchbot"
    twitchbot_dst = RCLONE_DEST_PATH / "aws" / "twitchbot"
    twitchbot_cmd = RCLONE_BASE + [
        str(twitchbot_src),
        str(twitchbot_dst),
        "--exclude",
        ".dotfiles/**",
    ]
    sh(twitchbot_cmd)
    print("Downloaded twitchbot")


def commit_notes():
    date = time.ctime()
    os.chdir(Path.home() / "Documents" / "notes")
    sh(["git", "add", "."])
    sh(["git", "commit", "-m", f"Update {date}"], check=False)
    print("Committed notes")


def choco_upgrade():
    sh(["choco", "upgrade", "all"])
    print("Upgraded Chocolatey packages")


def wsl_upgrade():
    sh(["wsl.exe", "sudo", "apt", "update"])
    sh(["wsl.exe", "sudo", "apt", "upgrade", "-y"])
    print("Updated apt packages in WSL")


def backup_c_drive(errors):
    shuffled_dirs = BACKUP_DIRS.copy()
    random.shuffle(shuffled_dirs)
    for backup_dir in shuffled_dirs:
        source_path = Path.home() / backup_dir
        try_task(lambda: backup_windows_dir(source_path), errors)
    print("Backed up C drive")


def backup_wsl():
    # WSLENV var is list of Windows environment vars to share with WSL.

    # Generate WSLENV
    env = os.environ.copy()
    if "WSLENV" in env:
        wslenv = env["WSLENV"]
    else:
        wslenv = ""
    for var_name in RESTIC_ENV_VARS.keys():
        wslenv += f":{var_name}"
    env["WSLENV"] = wslenv

    # Add Restic environment vars to Windows environment to run wsl.exe in
    for var, val in RESTIC_ENV_VARS.items():
        env[var] = val

    cmd = [
        "wsl.exe",
        "--shell-type",
        "none", # We don't want bash/zsh to try expanding our exclude glob patterns
        "/home/alex/.local/bin/restic",
        "backup",
        "/home/alex",
        "--tag",
        "WSL",
    ] + RESTIC_DEFAULT_ARGS
    sh(cmd, env=env)
    print("Backed up WSL")


def check_restic_integrity():
    # TODO once per week, do more complete but time-consuming integrity check
    env = os.environ.copy()
    for var, val in RESTIC_ENV_VARS.items():
        env[var] = val
    sh(["restic", "check"], env=env)


def do_backup_windows():
    errors = []

    try_task(commit_notes, errors)
    try_task(backup_aws, errors)
    try_task(choco_upgrade, errors)
    try_task(wsl_upgrade, errors)
    try_task(lambda: backup_c_drive(errors), errors)
    try_task(backup_wsl, errors)
    try_task(check_restic_integrity, errors)

    if len(errors) == 0:
        notify("Backup succeeded", "Hope you're having a nice day :)")
    else:
        subject = f'Backup failed! {len(errors)} error{"" if len(errors) == 1 else "s"}'
        msg = "".join(str(e) for e in errors).strip()
        notify(subject, msg)
    print("Reported backup errors")


if __name__ == "__main__":
    try:
        do_backup_windows()
    except Exception as e:
        notify("Backup failed: 1 error", e)
