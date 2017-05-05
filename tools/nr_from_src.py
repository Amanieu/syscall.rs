#!/usr/bin/env python3

import os
import re
import tempfile
import subprocess
import sys

from typing import Iterable, Set, Tuple

linux_path = '.'

SIMPLE_MATH = re.compile('^[()+0-9a-fx\s]*$')
NUMBER = re.compile('[0-9a-fx]+')

def load_table(path: str, arches: Set[str]):
    with open('{}/{}'.format(linux_path, path)) as f:
        for line in f:
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            nr, arch, name = line.split('\t', 4)[0:3]
            if arch in arches:
                yield (name, int(nr))

def eval_expr(expr: str) -> int:
    if not SIMPLE_MATH.match(expr):
        raise Exception('"{}" looks like an expression, but not a supported one'.format(expr))
    return sum(int(x.group(0), 0) for x in NUMBER.finditer(expr))


def load_headers(names: Iterable[Tuple[str, str]], arch: str, extra: str = ''):
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.h') as f:
        with tempfile.TemporaryDirectory() as temp_include_dir:
            os.mkdir('{}/asm'.format(temp_include_dir))
            with open('{}/asm/unistd-eabi.h'.format(temp_include_dir), 'w'):
                pass
            with open('{}/asm/unistd-common.h'.format(temp_include_dir), 'w'):
                pass

            f.write(extra)
            f.write('\n')
            f.write('#include <asm/unistd.h>\n')
            for prefix, name in names:
                f.write('gen_nr {prefix}{name} __{prefix}NR_{name}\n'.format(prefix=prefix, name=name))
            f.flush()
            lines = subprocess.check_output(['gcc', '-nostdinc',
                '-I', '{}/arch/{}/include/uapi'.format(linux_path, arch),
                '-I', '{}/include'.format(linux_path),
                '-I', temp_include_dir,
                '-P', # don't include line number markers, which make the output annoying to parse
                '-E', # only preprocess, don't compile
                f.name]).decode('utf-8').split('\n')

    for line in lines:
        if not line.startswith('gen_nr '):
            continue
        _, name, nr = line.split(' ', 2)
        if nr.startswith('__'):
            # unsupported on this arch
            continue
        if nr.startswith('('):
            nr = eval_expr(nr)
        yield (name, int(nr))


def main():
    RE_SYSCALL_NR=re.compile(r'\b__([A-Z]+_)?NR_([a-z0-9_]+)\b')
    names = set(x.groups() for x in RE_SYSCALL_NR.finditer(
        subprocess.check_output(['git', '--no-pager', 'grep', r'\<__\([A-Z]\+_\)\?NR_'], cwd=linux_path)
            .decode('utf-8')))
    if len(names) < 380:
        print("didn't find anywhere near enough syscalls; hack must have failed")
        subprocess.check_call(['git', '--no-pager', 'grep', r'\<__\([A-Z]\+_\)\?NR_'], cwd=linux_path)
        sys.exit(1)
    ARM_NAMES = ["breakpoint", "cacheflush", "usr26", "usr32", "set_tls"]
    numbers = {
            'linux-aarch64': dict(load_headers(names, 'arm64')),
            'linux-armeabi': dict(list(load_table('arch/arm/tools/syscall.tbl', {'common', 'eabi'})) + list(load_headers(names, 'arm', '#define __ARM_EABI__'))),
            'linux-mips': dict(load_headers(names, 'mips',
                '#define _MIPS_SIM _MIPS_SIM_ABI32')),
            'linux-mips64': dict(load_headers(names, 'mips',
                '#define _MIPS_SIM _MIPS_SIM_ABI64')),
            'linux-powerpc': dict(load_headers(names, 'powerpc',
                '#undef __arch64__')),
            'linux-powerpc64': dict(load_headers(names, 'powerpc',
                '#define __arch64__ 1\n#define __powerpc64__')),
            'linux-sparc64': dict(load_headers(names, 'sparc')),
            'linux-x86': dict(load_table('arch/x86/entry/syscalls/syscall_32.tbl', {'i386'})),
            'linux-x86_64': dict(load_table('arch/x86/entry/syscalls/syscall_64.tbl', {'common', '64'})),
            }

    for arch, nums in numbers.items():
        if not nums:
            continue
        with open('../src/platform/{}/nr.rs'.format(arch), 'w') as f:
            f.write('/* automatically generated by nr_from_src.py */\n\n')
            for name, nr in sorted(nums.items()):
                f.write('pub const {}: usize = {};\n'.format(name.upper(), nr))

if '__main__' == __name__:
    if len(sys.argv) > 1:
        linux_path = sys.argv[1]
    main()

