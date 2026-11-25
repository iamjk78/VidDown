"""Zastavení podprocesu ukončí i jeho potomky (sirotci po zrušení/pauze)."""
import asyncio
import os
import sys

import pytest

from viddown.resolvers import ProcHolder, spawn_proc


@pytest.mark.skipif(sys.platform == "win32", reason="skupiny procesů jsou POSIX")
def test_stop_kills_the_child_process_too():
    async def go():
        holder = ProcHolder()
        proc = await spawn_proc("sh", "-c", "sleep 30 & echo $!; wait", stdout=asyncio.subprocess.PIPE)
        await holder.attach(proc)
        child = int((await proc.stdout.readline()).decode().strip())
        await holder.stop()
        await asyncio.sleep(0.2)
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)                       # potomek už neběží
        assert proc.returncode is not None
    asyncio.run(go())
