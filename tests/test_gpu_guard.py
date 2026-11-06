"""GPU watchdog: parsing and limits, no GPU needed."""

from yellow_agent.tools.gpu_guard import kernel_trouble, over_limits, parse_memory

SMI = """
    FB Memory Usage
        Total                                          : 16311 MiB
        Reserved                                       : 373 MiB
        Used                                           : 673 MiB
        Free                                           : 15266 MiB
    BAR1 Memory Usage
        Total                                          : 256 MiB
        Used                                           : 18 MiB
        Free                                           : 238 MiB
    Conf Compute Protected Memory Usage
        Total                                          : 0 MiB
        Used                                           : 0 MiB
"""


def test_parse_memory_reads_fb_and_bar1():
    assert parse_memory(SMI) == {
        "fb_total": 16311, "fb_used": 673, "bar1_total": 256, "bar1_used": 18,
    }  # fmt: skip


def test_limits():
    assert over_limits({"bar1_used": 18, "fb_used": 673}, 200, 12000) is None
    assert "BAR1" in over_limits({"bar1_used": 201, "fb_used": 0}, 200, 12000)
    assert "VRAM" in over_limits({"bar1_used": 0, "fb_used": 12001}, 200, 12000)


def test_kernel_lines_that_trip():
    assert kernel_trouble("NVRM: dmaAllocMapping_GM107: can't alloc VA space for mapping.")
    assert kernel_trouble("NVRM: krcWatchdog_IMPL: RC watchdog: GPU is probably locked!")
    assert kernel_trouble("[drm:__nv_drm_gem_nvkms_map [nvidia_drm]] *ERROR* [nvidia-drm] x")
    assert not kernel_trouble("[UFW BLOCK] IN=wlan0 OUT= SRC=1.2.3.4")
