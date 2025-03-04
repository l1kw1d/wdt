from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
import os
import hashlib
import difflib
import subprocess
from random import randint
import shutil
import tempfile
import errno
import string
import random

# defaults (and file global)
receiver_binary = "_bin/wdt/wdt"
sender_binary = receiver_binary

def get_env(name):
    if name in os.environ:
        return os.environ[name]

def set_binaries():
    global receiver_binary, sender_binary
    sender = get_env('WDT_SENDER')
    if sender:
        sender_binary = sender
    receiver = get_env('WDT_RECEIVER')
    if receiver:
        receiver_binary = receiver
    print("Sender: " + sender_binary + " Receiver: " + receiver_binary)


def get_wdt_version():
    global receiver_binary
    dummy_cmd = receiver_binary + " --version"
    dummy_process = subprocess.Popen(dummy_cmd.split(),
                                     stdout=subprocess.PIPE)
    protocol_string = dummy_process.stdout.readline().strip()
    print("Receiver " + receiver_binary + " version is " + protocol_string)
    return protocol_string.split()[4]

def extend_wdt_options(cmd):
    extra_options = get_env('EXTRA_WDT_OPTIONS')
    if extra_options:
        print("extra options " + extra_options)
        cmd = cmd + " " + extra_options
    encryption_type = get_env('ENCRYPTION_TYPE')
    if encryption_type:
        print("encryption_type " + encryption_type)
        cmd = cmd + " -encryption_type=" + encryption_type
    enable_checksum = get_env('ENABLE_CHECKSUM')
    if enable_checksum:
        print("enable_checksum " + enable_checksum)
        cmd = cmd + " -enable_checksum=" + enable_checksum
    return cmd

def start_receiver(receiver_cmd, root_dir, test_count):
    receiver_cmd = extend_wdt_options(receiver_cmd)
    print("Receiver: " + receiver_cmd)
    server_log = "{0}/server{1}.log".format(root_dir, test_count)
    receiver_process = subprocess.Popen(receiver_cmd.split(),
                                        stdout=subprocess.PIPE,
                                        stderr=open(server_log, 'w'))
    connection_url = receiver_process.stdout.readline().strip()
    if not connection_url:
        print("ERR: Unable to get the connection url from receiver!")
    return (receiver_process, connection_url)

def run_sender(sender_cmd, root_dir, test_count):
    sender_cmd = extend_wdt_options(sender_cmd)
    # TODO: fix this to not use tee, this is python...
    sender_cmd = "bash -c \"set -o pipefail; " + sender_cmd \
                + " 2>&1 | tee {0}/client{1}.log\"".format(root_dir, test_count)
    print("Sender: " + sender_cmd)
    # return code of system is shifted by 8 bytes
    return os.system(sender_cmd) >> 8

def run_sender_arg(sender_arg, root_dir, test_count):
    global sender_binary
    return run_sender(sender_binary + " " + sender_arg, root_dir, test_count)

def start_receiver_arg(receiver_arg, root_dir, test_count):
    global receiver_binary
    print("Starting receiver " + receiver_binary)
    return start_receiver(receiver_binary + " " + receiver_arg,
                          root_dir, test_count)


def check_transfer_status(status, root_dir, test_count):
    if status:
        with open("{0}/server{1}.log".format(root_dir, test_count), 'r') as fin:
            print(fin.read())
        print("Transfer failed {0}".format(status))
        exit(status)

def check_logs_for_errors(root_dir, test_count, fail_errors):
    log_file = "%s/server%s.log" % (root_dir, test_count)
    server_log_contents = open(log_file).read()
    log_file = "%s/client%s.log" % (root_dir, test_count)
    client_log_contents = open(log_file).read()

    for fail_error in fail_errors:
        if fail_error in server_log_contents:
            print("%s found in logs %s" % (fail_error, log_file))
            exit(1)
        if fail_error in client_log_contents:
            print("%s found in logs %s" % (fail_error, log_file))
            exit(1)

def create_directory(root_dir):
    # race condition during stress test can happen even if we check first
    try:
        os.mkdir(root_dir)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise e
        pass

def create_test_directory(prefix):
    user = os.environ['USER']
    base_dir = prefix + "/wdtTest_" + user
    create_directory(base_dir)
    root_dir = tempfile.mkdtemp(dir=base_dir)
    print("Testing in {0}".format(root_dir))
    return root_dir

def generate_random_files(root_dir, total_size):
    create_directory(root_dir)
    cur_dir = os.getcwd()
    os.chdir(root_dir)
    seed_size = int(total_size / 70)
    for i in range(0, 4):
        file_name = "sample{0}".format(i)
        with open(file_name, 'wb') as fout:
            fout.write(os.urandom(seed_size))
    for i in range(0, 16):
        file_name = "file{0}".format(i)
        with open(file_name, 'wb') as fout:
            for j in range(0, 4):
                sample = randint(0, 3)
                sin = open("sample{0}".format(sample), 'rb')
                fout.write(sin.read())
    os.chdir(cur_dir)

def get_md5_for_file(file_path):
    return hashlib.md5(open(file_path, 'rb').read()).hexdigest()

def create_md5_for_directory(src_dir, md5_file_name):
    lines = []
    for root, dirs, files in os.walk(src_dir):
        for file in files:
            full_path = os.path.join(root, file)
            md5 = get_md5_for_file(full_path)
            lines.append("{0} {1}".format(md5, file))
    lines.sort()
    md5_in = open(md5_file_name, 'wb')
    for line in lines:
        md5_in.write(line + "\n")

def verify_transfer_success(root_dir, test_ids, skip_tests=set()):
    src_md5_path = os.path.join(root_dir, "src.md5")
    create_md5_for_directory(os.path.join(root_dir, "src"), src_md5_path)
    status = 0
    for i in test_ids:
        if i in skip_tests:
            print("Skipping verification of test %s" % (i))
            continue
        print("Verifying correctness for test {0}".format(i))
        print("Should be no diff")
        dst_dir = os.path.join(root_dir, "dst{0}".format(i))
        dst_md5_path = os.path.join(root_dir, "dst{0}.md5".format(i))
        create_md5_for_directory(dst_dir, dst_md5_path)
        diff = difflib.unified_diff(open(src_md5_path).readlines(),
                open(dst_md5_path).readlines())
        delta = ''.join(diff)
        if not delta:
            print("Found no diff for test {0}".format(i))
            if search_in_logs(root_dir, i, "PROTOCOL_ERROR"):
                status = 1
        else:
            print(delta)
            with open("{0}/server{1}.log".format(
                    root_dir, i), 'r') as fin:
                print(fin.read())
            status = 1
    if status == 0:
        print("Good run, deleting logs in " + root_dir)
        shutil.rmtree(root_dir)
    else:
        print("Bad run - keeping full logs and partial transfer in " + root_dir)
    return status

def search_in_logs(root_dir, i, str):
    found = False
    client_log = "{0}/client{1}.log".format(root_dir, i)
    server_log = "{0}/server{1}.log".format(root_dir, i)
    if str in open(client_log).read():
        print("Found {0} in {1}".format(str, client_log))
        found = True
    if str in open(server_log).read():
        print("Found {0} in {1}".format(str, server_log))
        found = True
    return found

def generate_encryption_key():
    return ''.join(random.choice(string.lowercase) for i in range(16))
