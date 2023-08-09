import math
import os
import re
import zlib
from io import BytesIO
from typing import BinaryIO

from nbt import nbt

from .block import Block
from .chunk import Chunk
from .errors import GZipChunkData, OutOfBoundsCoordinates
from .section import Section


class Region:
    """
    Read-write region

    Attributes
    ----------
    data: :class:`bytes`
        Region file (``.mca``) as bytes
    chunks: List[:class:`anvil.Chunk`]
        List of chunks in this region
    x: :class:`int`
    z: :class:`int`
    """

    __slots__ = ("data", "x", "z", "chunks")

    def __init__(self, data: bytes, x=None, z=None):
        """Makes a Region object from data, which is the region file content"""
        self.data = data
        self.x = x
        self.z = z

        # read chunks from data
        self.chunks: list[Chunk] = [None] * 1024

        for j in range(z * 32, z * 32 + 32):
            for i in range(x * 32, x * 32 + 32):
                cnk = Chunk(self.chunk_data(i, j), i, j)
                self.chunks[(j % 32) * 32 + (i % 32)] = cnk
        return

    def inside(self, x: int, y: int, z: int, chunk: bool = False) -> bool:
        """
        Returns if the given coordinates are inside this region

        Parameters
        ----------
        int x, y, z
            Coordinates
        chunk
            Whether coordinates are global or chunk coordinates
        """
        factor = 32 if chunk else 512
        rx = x // factor
        rz = z // factor
        return not (rx != self.x or rz != self.z or y not in range(-64, 320))

    def add_chunk(self, chunk: Chunk):
        """
        Adds given chunk to this region.
        Will overwrite if a chunk already exists in this location

        Parameters
        ----------
        chunk: :class:`Chunk`

        Raises
        ------
        anvil.OutOfBoundCoordidnates
            If the chunk (x, z) is not inside this region
        """
        if not self.inside(chunk.x, 0, chunk.z, chunk=True):
            raise OutOfBoundsCoordinates(f"Chunk ({chunk.x}, {chunk.z}) is not inside this region")
        self.chunks[chunk.z % 32 * 32 + chunk.x % 32] = chunk

    def get_chunk(self, x: int, z: int) -> Chunk:
        """
        Returns the chunk at given chunk coordinates

        Parameters
        ----------
        int x, z
            Chunk's coordinates

        Raises
        ------
        anvil.OutOfBoundCoordidnates
            If the chunk (x, z) is not inside this region

        :rtype: :class:`anvil.Chunk`
        """
        if not self.inside(x, 0, z, chunk=True):
            raise OutOfBoundsCoordinates(f"Chunk ({x}, {z}) is not inside this region")
        return self.chunks[z % 32 * 32 + x % 32]

    def add_section(self, section: Section, x: int, z: int, replace: bool):
        """
        Adds section to chunk at (x, z).
        Same as ``Chunk.add_section(section)``

        Parameters
        ----------
        section: :class:`Section`
            Section to add
        int x, z
            Chunk's coordinate
        replace
            Whether to replace section if it already exists in the chunk

        Raises
        ------
        anvil.OutOfBoundsCoordinates
            If the chunk (x, z) is not inside this region
        """
        if not self.inside(x, 0, z, chunk=True):
            raise OutOfBoundsCoordinates(f"Chunk ({x}, {z}) is not inside this region")
        chunk = self.chunks[z % 32 * 32 + x % 32]
        if chunk is None:
            chunk = Chunk(x, z)
            self.add_chunk(chunk)
        chunk.add_section(section, replace)

    def set_block(self, block: Block, x: int, y: int, z: int):
        """
        Sets block at given coordinates.
        New chunk is made if it doesn't exist.

        Parameters
        ----------
        block: :class:`Block`
            Block to place
        int x, y, z
            Coordinates

        Raises
        ------
        anvil.OutOfBoundsCoordinates
            If the block (x, y, z) is not inside this region
        """
        if not self.inside(x, y, z):
            raise OutOfBoundsCoordinates(f"Block ({x}, {y}, {z}) is not inside this region")
        cx = x // 32
        cz = z // 32
        chunk = self.get_chunk(cx, cz)
        if chunk is None:
            chunk = Chunk(cx, cz)
            self.add_chunk(chunk)
        chunk.set_block(block, x % 16, y, z % 16)

    def get_block(self, x: int, y: int, z: int):
        """
        Sets block at given coordinates.
        New chunk is made if it doesn't exist.

        Parameters
        ----------
        block: :class:`Block`
            Block to place
        int x, y, z
            Coordinates

        Raises
        ------
        anvil.OutOfBoundsCoordinates
            If the block (x, y, z) is not inside this region
        """
        if not self.inside(x, y, z):
            raise OutOfBoundsCoordinates(f"Block ({x}, {y}, {z}) is not inside this region")
        cx = x // 32
        cz = z // 32
        chunk = self.get_chunk(cx, cz)
        if chunk is None:
            return Block.from_name("minecraft:air")
        return chunk.get_block(x % 16, y, z % 16)

    def set_if_inside(self, block: Block, x: int, y: int, z: int):
        """
        Helper function that only sets
        the block if ``self.inside(x, y, z)`` is true

        Parameters
        ----------
        block: :class:`Block`
            Block to place
        int x, y, z
            Coordinates
        """
        if self.inside(x, y, z):
            self.set_block(block, x, y, z)

    # methods from raw data
    @staticmethod
    def header_offset(chunk_x: int, chunk_z: int) -> int:
        """
        Returns the byte offset for given chunk in the header

        Parameters
        ----------
        chunk_x
            Chunk's X value
        chunk_z
            Chunk's Z value
        """
        return 4 * (chunk_x % 32 + chunk_z % 32 * 32)

    def chunk_location(self, chunk_x: int, chunk_z: int) -> tuple[int, int]:
        """
        Returns the chunk offset in the 4KiB sectors from the start of the file,
        and the length of the chunk in sectors of 4KiB

        Will return ``(0, 0)`` if chunk hasn't been generated yet

        Parameters
        ----------
        chunk_x
            Chunk's X value
        chunk_z
            Chunk's Z value
        """
        b_off = self.header_offset(chunk_x, chunk_z)
        off = int.from_bytes(self.data[b_off : b_off + 3], byteorder="big")
        sectors = self.data[b_off + 3]
        return (off, sectors)

    def chunk_data(self, chunk_x: int, chunk_z: int) -> nbt.NBTFile:
        """
        Returns the NBT data for a chunk

        Parameters
        ----------
        chunk_x
            Chunk's X value
        chunk_z
            Chunk's Z value

        Raises
        ------
        anvil.GZipChunkData
            If the chunk's compression is gzip
        """
        off = self.chunk_location(chunk_x, chunk_z)
        # (0, 0) means it hasn't generated yet, aka it doesn't exist yet
        if off == (0, 0):
            return
        off = off[0] * 4096
        length = int.from_bytes(self.data[off : off + 4], byteorder="big")
        compression = self.data[off + 4]  # 2 most of the time
        if compression == 1:
            raise GZipChunkData("GZip is not supported")
        compressed_data = self.data[off + 5 : off + 5 + length - 1]
        return nbt.NBTFile(buffer=BytesIO(zlib.decompress(compressed_data)))

    @classmethod
    def from_file(cls, file: str | BinaryIO, x=None, z=None):
        """
        Creates a new region with the data from reading the given file

        Parameters
        ----------
        file
            Either a file path or a file object
        """
        if isinstance(file, str):
            matches = re.findall("-?\\d+", os.path.basename(file))
            if len(matches) != 2:
                print(f"Coulnd't extract region x and z from region file {file}")
                return

            with open(file, "rb") as f:
                return cls(data=f.read(), x=int(matches[0]), z=int(matches[1]))
        else:
            if x is None or z is None:
                print("If providing file object also provide x and z of region")
                return None
            return cls(data=file.read(), x=x, z=z)

    def save(self, file: str | BinaryIO = None) -> bytes:
        """
        Returns the region as bytes with
        the anvil file format structure,
        aka the final ``.mca`` file.

        Parameters
        ----------
        file
            Either a path or a file object, if given region
            will be saved there.
        """
        # Store all the chunks data as zlib compressed nbt data
        chunks_data = []
        for chunk in self.chunks:
            if chunk is None:
                chunks_data.append(None)
                continue
            chunk_data = BytesIO()
            nbt_data = chunk.data if not chunk.constructed and chunk.data is not None else chunk.save()
            nbt_data.write_file(buffer=chunk_data)
            chunk_data.seek(0)
            chunk_data = zlib.compress(chunk_data.read())
            chunks_data.append(chunk_data)

        # This is what is added after the location and timestamp header
        chunks_bytes = b""
        offsets = []
        for chunk in chunks_data:
            if chunk is None:
                offsets.append(None)
                continue
            # 4 bytes are for length, b'\x02' is the compression type which is 2 since its using zlib
            to_add = (len(chunk) + 1).to_bytes(4, "big") + b"\x02" + chunk

            # offset in 4KiB sectors
            sector_offset = len(chunks_bytes) // 4096
            sector_count = math.ceil(len(to_add) / 4096)
            offsets.append((sector_offset, sector_count))

            # Padding to be a multiple of 4KiB long
            to_add += bytes(4096 - (len(to_add) % 4096))
            chunks_bytes += to_add

        locations_header = b""
        for offset in offsets:
            # None means the chunk is not an actual chunk in the region
            # and will be 4 null bytes, which represents non-generated chunks to minecraft
            if offset is None:
                locations_header += bytes(4)
            else:
                # offset is (sector offset, sector count)
                locations_header += (offset[0] + 2).to_bytes(3, "big") + offset[1].to_bytes(1, "big")

        # Set them all as 0
        timestamps_header = bytes(4096)

        final = locations_header + timestamps_header + chunks_bytes

        # Pad file to be a multiple of 4KiB in size
        # as Minecraft only accepts region files that are like that
        final += bytes(4096 - (len(final) % 4096))
        assert len(final) % 4096 == 0  # just in case

        # Save to a file if it was given
        if file:
            if isinstance(file, str):
                with open(file, "wb") as f:
                    f.write(final)
            else:
                file.write(final)
        return final
