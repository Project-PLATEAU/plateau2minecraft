from collections.abc import Generator

from nbt import nbt

from .biome import Biome
from .block import Block, OldBlock
from .errors import OutOfBoundsCoordinates, SectionAlreadyExists
from .section import Section

# This is the final version before the Minecraft overhaul that includes the
# 1.18 expansion of the world's vertical height from -64 to 319
_VERSION_1_17_1 = 2730

# This version removes block state value stretching from the storage
# so a block value isn't in multiple elements of the array
_VERSION_20w17a = 2529

# This version changes how biomes are stored to allow for biomes at different heights
# https://minecraft.fandom.com/wiki/Java_Edition_19w36a
_VERSION_19w36a = 2203

# This is the version where "The Flattening" (https://minecraft.gamepedia.com/Java_Edition_1.13/Flattening) happened
# where blocks went from numeric ids to namespaced ids (namespace:block_id)
_VERSION_17w47a = 1451


def bin_append(a, b, length=None):
    """
    Appends number a to the left of b
    bin_append(0b1, 0b10) = 0b110
    """
    length = length or b.bit_length()
    return (a << length) | b


def nibble(byte_array, index):
    value = byte_array[index // 2]
    if index % 2:
        return value >> 4
    else:
        return value & 0b1111


def _states_from_section(section: nbt.TAG_Compound) -> list:
    # BlockStates is an array of 64 bit numbers
    # that holds the blocks index on the palette list
    states = section["block_states"]["data"] if "block_states" in section else section["BlockStates"]

    # makes sure the number is unsigned
    # by adding 2^64
    # could also use ctypes.c_ulonglong(n).value but that'd require an extra import

    return [state if state >= 0 else states + 2**64 for state in states.value]


def _palette_from_section(section: nbt.TAG_Compound) -> nbt.TAG_List:
    if "block_states" in section:
        return section["block_states"]["palette"]
    else:
        return section["Palette"]


def _section_height_range(version: int | None) -> range:
    if version is not None and version > _VERSION_17w47a:
        return range(-4, 20)
    else:
        return range(16)


class Chunk:
    """
    Represents a chunk from a ``.mca`` file.

    Attributes
    ----------
    x: :class:`int`
        Chunk's X position
    z: :class:`int`
        Chunk's Z position
    version: :class:`int`
        Version of the chunk NBT structure
    data: :class:`nbt.TAG_Compound`
        Raw NBT data of the chunk
    tile_entities: :class:`nbt.TAG_Compound`
        ``self.data['TileEntities']`` as an attribute for easier use
    sections: List[:class:`anvil.EmptySection`]
        List of all the sections in this chunk
    """

    __slots__ = ("version", "data", "x", "z", "tile_entities", "sections", "constructed")

    def __init__(self, nbt_data: nbt.NBTFile, x=None, z=None, version=None):
        # 2 options:
        # data is None: empty chunk, init manually
        if nbt_data is None:
            self.data = None
            if version is None:
                # TODO: versioning if data is None?
                self.version = _VERSION_1_17_1 + 1
            else:
                self.version = version
            self.x = x
            self.z = z
            self.tile_entities = None

            self.sections = [None] * len(_section_height_range(self.version))

            self.constructed = True

        # data is not None: read in chunk
        else:
            try:
                self.version = nbt_data["DataVersion"].value
            except KeyError:
                # Version is pre-1.9 snapshot 15w32a, so world does not have a Data Version.
                # See https://minecraft.fandom.com/wiki/Data_version
                self.version = None

            if self.version > _VERSION_1_17_1:
                self.data = nbt_data
                self.tile_entities = self.data["block_entities"]
            else:
                self.data = nbt_data["Level"]
                self.tile_entities = self.data["TileEntities"]
            self.x = self.data["xPos"].value
            self.z = self.data["zPos"].value
            if (x != self.x) or (z != self.z):
                print("ALERT: X/Z MISMATCH IN CHUNK")
                print(f"Assigned x: {x}, actual x: {self.x}")
                print(f"Assigned z: {z}, actual x: {self.z}")
            self.sections = [None] * len(_section_height_range(self.version))

            self.constructed = False

    def get_sections_from_data(self):
        """
        Returns the sections read from data in editable format
        """
        if "sections" in self.data:
            sec_data = self.data["sections"]
        else:
            try:
                sec_data = self.data["Sections"]
            except KeyError:
                return None

        self.sections = [None] * len(_section_height_range(self.version))
        for data in sec_data:
            new_sec = Section(data, self.version)
            self.sections[new_sec.y + 4] = new_sec

    def add_section(self, section: Section, replace: bool = True):
        """
        Adds a section to the chunk

        Parameters
        ----------
        section
            Section to add
        replace
            Whether to replace section if one at same Y already exists

        Raises
        ------
        anvil.EmptySectionAlreadyExists
            If ``replace`` is ``False`` and section with same Y already exists in this chunk
        """
        if not self.constructed:
            self.get_sections_from_data()
            self.constructed = True
        if self.sections[section.y + 4] and not replace:
            raise SectionAlreadyExists(f"EmptySection (Y={section.y}) already exists in this chunk")
        self.sections[section.y + 4] = section

    def get_block(self, x: int, y: int, z: int) -> Block:
        """
        Gets the block at given coordinates

        Parameters
        ----------
        int x, z
            In range of 0 to 15
        y
            In range of -64 to 319

        Raises
        ------
        anvil.OutOfBoundCoordidnates
            If X, Y or Z are not in the proper range

        Returns
        -------
        block : :class:`anvil.Block` or None
            Returns ``None`` if the section is empty, meaning the block
            is most likely an air block.
        """
        if x not in range(16):
            raise OutOfBoundsCoordinates(f"X ({x!r}) must be in range of 0 to 15")
        if z not in range(16):
            raise OutOfBoundsCoordinates(f"Z ({z!r}) must be in range of 0 to 15")
        # TODO: make dependent on version
        if y not in range(-64, 320):
            raise OutOfBoundsCoordinates(f"Y ({y!r}) must be in range of -64 to 319")
        if not self.constructed:
            return self.get_block_from_data(x, y, z)
        section = self.sections[(y // 16) + 4]
        if section is None:
            return
        return section.get_block(x, y % 16, z)

    def set_block(self, block: Block, x: int, y: int, z: int):
        """
        Sets block at given coordinates

        Parameters
        ----------
        int x, z
            In range of 0 to 15
        y
            In range of -64 to 319

        Raises
        ------
        anvil.OutOfBoundCoordidnates
            If X, Y or Z are not in the proper range
        """
        if x not in range(16):
            raise OutOfBoundsCoordinates(f"X ({x!r}) must be in range of 0 to 15")
        if z not in range(16):
            raise OutOfBoundsCoordinates(f"Z ({z!r}) must be in range of 0 to 15")
        # TODO: make dependent on version
        if y not in range(-64, 320):
            raise OutOfBoundsCoordinates(f"Y ({y!r}) must be in range of -64 to 320")
        if not self.constructed:
            self.get_sections_from_data()
            self.constructed = True
        section = self.sections[(y // 16) + 4]
        if section is None:
            section = Section(data=None, chunk_version=self.version, y=y // 16)
            self.add_section(section)
        section.set_block(block, x, y % 16, z)

    def set_biome(self, biome: Biome):
        for section in self.sections:
            if section is not None:
                section.set_biome(biome)

    def save(self) -> nbt.NBTFile:
        """
        Saves the chunk data to a :class:`NBTFile` with format depending on version

        Notes
        -----
        If changed, does not contain most data a regular chunk would have,
        but minecraft stills accept it.
        """
        if not self.constructed:
            return self.data

        # TODO: support more versions ?
        if self.version > _VERSION_1_17_1:
            return self.save_new()
        else:
            return self.save_old()

    def save_old(self) -> nbt.NBTFile:
        """
        Saves the chunk data to a :class:`NBTFile`

        Notes
        -----
        Does not contain most data a regular chunk would have,
        but minecraft stills accept it.
        """
        root = nbt.NBTFile()
        root.tags.append(nbt.TAG_Int(name="DataVersion", value=self.version))
        level = nbt.TAG_Compound()
        # Needs to be in a separate line because it just gets
        # ignored if you pass it as a kwarg in the constructor
        level.name = "Level"
        level.tags.extend(
            [
                nbt.TAG_List(name="Entities", type=nbt.TAG_Compound),
                nbt.TAG_List(name="TileEntities", type=nbt.TAG_Compound),
                nbt.TAG_List(name="LiquidTicks", type=nbt.TAG_Compound),
                nbt.TAG_Int(name="xPos", value=self.x),
                nbt.TAG_Int(name="zPos", value=self.z),
                nbt.TAG_Long(name="LastUpdate", value=0),
                nbt.TAG_Long(name="InhabitedTime", value=0),
                nbt.TAG_Byte(name="isLightOn", value=1),
                nbt.TAG_String(name="Status", value="full"),
            ]
        )
        sections = nbt.TAG_List(name="Sections", type=nbt.TAG_Compound)
        biomes = nbt.TAG_Int_Array(name="Biomes")

        biomes.value = [_get_legacy_biome_id(biome) for biome in self.biomes]
        for s in self.sections:
            if s:
                p = s.palette()
                # Minecraft does not save sections that are just air
                # So we can just skip them
                if len(p) == 1 and p[0].name() == "minecraft:air":
                    continue
                sections.tags.append(s.save(new=False))
        level.tags.append(sections)
        level.tags.append(biomes)
        root.tags.append(level)
        return root

    def save_new(self) -> nbt.NBTFile:
        """
        Saves the chunk data to a :class:`NBTFile`, using new formatting

        Notes
        -----
        Does not contain most data a regular chunk would have,
        but minecraft stills accept it.
        """
        root = nbt.NBTFile()
        root.tags.append(nbt.TAG_Int(name="DataVersion", value=self.version))
        sections = nbt.TAG_Compound()
        # Needs to be in a separate line because it just gets
        # ignored if you pass it as a kwarg in the constructor
        sections = nbt.TAG_List(name="sections", type=nbt.TAG_Compound)

        for s in self.sections:
            if s:
                sections.tags.append(s.save())
        root.tags.append(sections)

        root.tags.extend(
            [
                nbt.TAG_List(name="block_entities", type=nbt.TAG_Compound),
                nbt.TAG_List(name="block_ticks", type=nbt.TAG_Compound),
                nbt.TAG_List(name="fluid_ticks", type=nbt.TAG_Compound),
                nbt.TAG_Long(name="LastUpdate", value=0),
                nbt.TAG_Long(name="InhabitedTime", value=0),
                nbt.TAG_Byte(name="isLightOn", value=1),
                nbt.TAG_Int(name="xPos", value=self.x),
                nbt.TAG_Int(name="yPos", value=-3),
                nbt.TAG_Int(name="zPos", value=self.z),
                nbt.TAG_String(name="Status", value="full"),
            ]
        )
        return root

    # methods on raw data

    def get_section(self, y: int) -> nbt.TAG_Compound:
        """
        Returns the section at given y index
        can also return nothing if section is missing, aka it's empty

        Parameters
        ----------
        y
            Section Y index

        Raises
        ------
        anvil.OutOfBoundsCoordinates
            If Y is not in range of 0 to 15
        """
        section_range = _section_height_range(self.version)
        if y not in section_range:
            raise OutOfBoundsCoordinates(
                f"Y ({y!r}) must be in range of " f"{section_range.start} to {section_range.stop}"
            )

        if "sections" in self.data:
            sections = self.data["sections"]
        else:
            try:
                sections = self.data["Sections"]
            except KeyError:
                return None

        for section in sections:
            if section["Y"].value == y:
                return section

    def get_palette(self, section: int | nbt.TAG_Compound) -> tuple[Block]:
        """
        Returns the block palette for given section

        Parameters
        ----------
        section
            Either a section NBT tag or an index


        :rtype: Tuple[:class:`anvil.Block`]
        """
        if isinstance(section, int):
            section = self.get_section(section)
        if section is None:
            return
        palette = _palette_from_section(section)
        return tuple(Block.from_palette(i) for i in palette)

    def get_biome(self, x: int, y: int, z: int) -> Biome:
        """
        Returns the biome in the given coordinates

        Parameters
        ----------
        int x, y, z
            Biome's coordinates in the chunk

        Raises
        ------
        anvil.OutOfBoundCoordidnates
            If X, Y or Z are not in the proper range

        :rtype: :class:`anvil.Biome`
        """
        section_range = _section_height_range(self.version)
        if x not in range(16):
            raise OutOfBoundsCoordinates(f"X ({x!r}) must be in range of 0 to 15")
        if z not in range(16):
            raise OutOfBoundsCoordinates(f"Z ({z!r}) must be in range of 0 to 15")
        if y // 16 not in section_range:
            raise OutOfBoundsCoordinates(
                f"Y ({y!r}) must be in range of " f"{section_range.start * 16} to {section_range.stop * 16 - 1}"
            )

        if "Biomes" not in self.data:
            # Each biome index refers to a 4x4x4 volumes here so we do integer division by 4
            section = self.get_section(y // 16)
            biomes = section["biomes"]
            biomes_palette = biomes["palette"]
            if "data" in biomes:
                biomes = biomes["data"]
            else:
                # When there is only one biome in the section of the palette 'data'
                # is not present
                return Biome.from_name(biomes_palette[0].value)

            index = ((y % 16 // 4) * 4 * 4) + (z // 4) * 4 + (x // 4)
            bits = (len(biomes_palette) - 1).bit_length()
            state = index * bits // 64
            data = biomes[state]

            # shift the number to the right to remove the left over bits
            # and shift so the i'th biome is the first one
            shifted_data = data >> ((bits * index) % 64)

            # if there aren't enough bits it means the rest are in the next number
            if 64 - ((bits * index) % 64) < bits:
                data = biomes[state + 1]

                # get how many bits are from a palette index of the next biome
                leftover = (bits - ((state + 1) * 64 % bits)) % bits

                # Make sure to keep the length of the bits in the first state
                # Example: bits is 5, and leftover is 3
                # Next state                Current state (already shifted)
                # 0b101010110101101010010   0b01
                # will result in bin_append(0b010, 0b01, 2) = 0b01001
                shifted_data = bin_append(data & 2**leftover - 1, shifted_data, bits - leftover)

            palette_id = shifted_data & 2**bits - 1
            return Biome.from_name(biomes_palette[palette_id].value)

        else:
            biomes = self.data["Biomes"]
            if self.version < _VERSION_19w36a:
                # Each biome index refers to a column stored Z then X.
                index = z * 16 + x
            else:
                # https://minecraft.fandom.com/wiki/Java_Edition_19w36a
                # Get index on the biome list with the order YZX
                # Each biome index refers to a 4x4 areas here so we do integer division by 4
                index = (y // 4) * 4 * 4 + (z // 4) * 4 + (x // 4)
            biome_id = biomes[index]
            return Biome.from_numeric_id(biome_id)

    def get_block_from_data(
        self, x: int, y: int, z: int, section: int | nbt.TAG_Compound = None, force_new: bool = False
    ):
        """
        Returns the block in the given coordinates

        Parameters
        ----------
        int x, y, z
            Block's coordinates in the chunk
        section : int
            Either a section NBT tag or an index. If no section is given,
            assume Y is global and use it for getting the section.
        force_new
            Always returns an instance of Block if True, otherwise returns type OldBlock for pre-1.13 versions.
            Defaults to False

        Raises
        ------
        anvil.OutOfBoundCoordidnates
            If X, Y or Z are not in the proper range

        :rtype: :class:`anvil.Block`
        """
        if x not in range(16):
            raise OutOfBoundsCoordinates(f"X ({x!r}) must be in range of 0 to 15")
        if z not in range(16):
            raise OutOfBoundsCoordinates(f"Z ({z!r}) must be in range of 0 to 15")
        section_range = _section_height_range(self.version)
        if y // 16 not in section_range:
            raise OutOfBoundsCoordinates(
                f"Y ({y!r}) must be in range of " f"{section_range.start * 16} to {section_range.stop * 16 - 1}"
            )

        if section is None:
            section = self.get_section(y // 16)
            # global Y to section Y
            y %= 16

        if self.version is None or self.version < _VERSION_17w47a:
            # Explained in depth here https://minecraft.gamepedia.com/index.php?title=Chunk_format&oldid=1153403#Block_format

            if section is None or "Blocks" not in section:
                if force_new:
                    return Block.from_name("minecraft:air")
                else:
                    return OldBlock(0)

            index = y * 16 * 16 + z * 16 + x

            block_id = section["Blocks"][index]
            if "Add" in section:
                block_id += nibble(section["Add"], index) << 8

            block_data = nibble(section["Data"], index)

            block = OldBlock(block_id, block_data)
            if force_new:
                return block.convert()
            else:
                return block

        # If its an empty section its most likely an air block
        if section is None:
            return Block.from_name("minecraft:air")
        try:
            states = _states_from_section(section)
        except KeyError:
            return Block.from_name("minecraft:air")

        # Number of bits each block is on BlockStates
        # Cannot be lower than 4
        palette = _palette_from_section(section)

        bits = max((len(palette) - 1).bit_length(), 4)

        # Get index on the block list with the order YZX
        index = y * 16 * 16 + z * 16 + x
        # in 20w17a and newer blocks cannot occupy more than one element on the BlockStates array
        stretches = self.version is None or self.version < _VERSION_20w17a

        # get location in the BlockStates array via the index
        state = index * bits // 64 if stretches else index // (64 // bits)

        data = states[state]

        if stretches:
            # shift the number to the right to remove the left over bits
            # and shift so the i'th block is the first one
            shifted_data = data >> ((bits * index) % 64)
        else:
            shifted_data = data >> (index % (64 // bits) * bits)

        # if there aren't enough bits it means the rest are in the next number
        if stretches and 64 - ((bits * index) % 64) < bits:
            data = states[state + 1]

            # get how many bits are from a palette index of the next block
            leftover = (bits - ((state + 1) * 64 % bits)) % bits

            # Make sure to keep the length of the bits in the first state
            # Example: bits is 5, and leftover is 3
            # Next state                Current state (already shifted)
            # 0b101010110101101010010   0b01
            # will result in bin_append(0b010, 0b01, 2) = 0b01001
            shifted_data = bin_append(data & 2**leftover - 1, shifted_data, bits - leftover)

        # get `bits` least significant bits
        # which are the palette index
        palette_id = shifted_data & 2**bits - 1
        return Block.from_palette(palette[palette_id])

    # below: untouched for now, can stay or change to read data from sections

    def stream_blocks(
        self,
        index: int = 0,
        section: int | nbt.TAG_Compound = None,
        force_new: bool = False,
    ) -> Generator[Block, None, None]:
        """
        Returns a generator for all the blocks in given section

        Parameters
        ----------
        index
            At what block to start from.

            To get an index from (x, y, z), simply do:

            ``y * 256 + z * 16 + x``
        section
            Either a Y index or a section NBT tag.
        force_new
            Always returns an instance of Block if True, otherwise returns type OldBlock for pre-1.13 versions.
            Defaults to False

        Raises
        ------
        anvil.OutOfBoundCoordidnates
            If `section` is not in the range of 0 to 15

        Yields
        ------
        :class:`anvil.Block`
        """

        if isinstance(section, int):
            section_range = _section_height_range(self.version)
            if section not in section_range:
                raise OutOfBoundsCoordinates(
                    f"section ({section!r}) must be in range of " f"{section_range.start} to {section_range.stop}"
                )

        # For better understanding of this code, read get_block()'s source

        if section is None or isinstance(section, int):
            section = self.get_section(section or 0)

        if self.version < _VERSION_17w47a:
            if section is None or "Blocks" not in section:
                air = Block.from_name("minecraft:air") if force_new else OldBlock(0)
                for _ in range(4096):
                    yield air
                return

            while index < 4096:
                block_id = section["Blocks"][index]
                if "Add" in section:
                    block_id += nibble(section["Add"], index) << 8

                block_data = nibble(section["Data"], index)

                block = OldBlock(block_id, block_data)
                if force_new:
                    yield block.convert()
                else:
                    yield block

                index += 1
            return

        air = Block.from_name("minecraft:air")
        if section is None:
            for _ in range(4096):
                yield air
            return
        try:
            states = _states_from_section(section)
        except KeyError:
            for _ in range(4096):
                yield air
            return

        palette = _palette_from_section(section)
        bits = max((len(palette) - 1).bit_length(), 4)

        stretches = self.version < _VERSION_20w17a

        state = index * bits // 64 if stretches else index // (64 // bits)

        data = states[state]

        bits_mask = 2**bits - 1

        offset = bits * index % 64 if stretches else index % (64 // bits) * bits

        data_len = 64 - offset
        data >>= offset

        while index < 4096:
            if data_len < bits:
                state += 1
                new_data = states[state]

                if stretches:
                    leftover = data_len
                    data_len += 64

                    data = bin_append(new_data, data, leftover)
                else:
                    data = new_data
                    data_len = 64

            palette_id = data & bits_mask
            yield Block.from_palette(palette[palette_id])

            index += 1
            data >>= bits
            data_len -= bits

    def stream_chunk(self, index: int = 0, section: int | nbt.TAG_Compound = None) -> Generator[Block, None, None]:
        """
        Returns a generator for all the blocks in the chunk

        This is a helper function that runs Chunk.stream_blocks from section 0 to 15

        Yields
        ------
        :class:`anvil.Block`
        """
        for section in _section_height_range(self.version):
            for block in self.stream_blocks(section=section):
                yield block

    def get_tile_entity(self, x: int, y: int, z: int) -> nbt.TAG_Compound | None:
        """
        Returns the tile entity at given coordinates, or ``None`` if there isn't a tile entity

        To iterate through all tile entities in the chunk, use :class:`Chunk.tile_entities`
        """
        for tile_entity in self.tile_entities:
            t_x, t_y, t_z = (tile_entity[k].value for k in "xyz")
            if x == t_x and y == t_y and z == t_z:
                return tile_entity
