from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

CHIP_CAPACITY = 17     # usables por chip
CHIP_TOTAL = 20        # total: 20 (últimos 3 reservados)
CHIPS_PER_HOST = 2
HOST_CAPACITY = CHIP_CAPACITY * CHIPS_PER_HOST

@dataclass(frozen=True)
class VMType:
    vnf: str
    vnfc: str
    def key(self) -> Tuple[str, str]:
        return (self.vnf, self.vnfc)

@dataclass
class VM:
    idx: int
    vm_type: VMType
    color: str
    size: int
    az: str
    anti: int
    inst: int

@dataclass
class Placement:
    vm: VM
    host_id: int
    chip_idx: int   # 0/1
    start: int      # para dibujar
    end: int

@dataclass
class ChipResult:
    items: List[Placement] = field(default_factory=list)
    used: int = 0

@dataclass
class HostResult:
    id: int
    az: str
    chips: List[ChipResult]
    @property
    def used(self) -> int:
        return sum(c.used for c in self.chips)
    @property
    def capacity(self) -> int:
        return HOST_CAPACITY
