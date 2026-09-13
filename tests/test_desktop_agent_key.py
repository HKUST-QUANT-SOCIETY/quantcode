"""Exercise the real desktop key importer with an isolated, unlocked SSH Agent."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import pytest


@pytest.mark.skipif(os.name == 'nt' or not shutil.which('bun'), reason='requires Unix OpenSSH and Bun')
def test_unlocked_encrypted_key_is_reused_without_reading_its_passphrase():
    module = Path(__file__).resolve().parents[1] / 'frontend/packages/desktop/src/main/quantcode-identity.ts'
    with tempfile.TemporaryDirectory(prefix='qc-agent-key-', dir='/tmp') as directory:
        root = Path(directory)
        key, socket = root / 'id_ed25519', root / 'agent'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', 'fixture-pass', '-f', str(key)], check=True, capture_output=True)
        askpass = root / 'askpass'
        askpass.write_text("#!/bin/sh\nprintf '%s\\n' 'fixture-pass'\n")
        askpass.chmod(0o700)
        agent = subprocess.Popen(['ssh-agent', '-D', '-a', str(socket)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while not socket.exists():
                if time.monotonic() > deadline:
                    raise RuntimeError('isolated agent did not start')
                time.sleep(.01)
            env = {**os.environ, 'SSH_AUTH_SOCK': str(socket), 'SSH_ASKPASS': str(askpass), 'SSH_ASKPASS_REQUIRE': 'force', 'DISPLAY': ':0'}
            subprocess.run(['ssh-add', str(key)], env=env, stdin=subprocess.DEVNULL, capture_output=True, check=True)
            expected = subprocess.check_output(['ssh-keygen', '-lf', str(key) + '.pub'], text=True).split()[1]
            env['SSH_ASKPASS_REQUIRE'] = 'never'
            script = 'const {importKey}=await import(process.argv[1]); const value=await importKey({url:"http://127.0.0.1"},process.argv[2]); console.log(JSON.stringify(value));'
            result = subprocess.run(['bun', '-e', script, str(module), str(key)], env=env, stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=15, check=True)
            assert json.loads(result.stdout)['fingerprint'] == expected
            # Cold encrypted keys fail promptly with an actionable unlock message.
            subprocess.run(['ssh-add', '-D'], env=env, capture_output=True, check=True)
            failure = subprocess.run(['bun', '-e', script, str(module), str(key)], env=env, stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=15)
            assert failure.returncode != 0
            assert '私钥需要解锁' in failure.stderr
        finally:
            agent.terminate()
            agent.wait(timeout=5)
