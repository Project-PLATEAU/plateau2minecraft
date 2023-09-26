import array
from struct import Struct

from nbt import nbt

from .biome import Biome
from .block import Block
from .errors import OutOfBoundsCoordinates

# This is the final version before the Minecraft overhaul that includes the
# 1.18 expansion of the world's vertical height from -64 to 319
_VERSION_1_17_1 = 2730

# This version removes block state value stretching from the storage
# so a block value isn't in multiple elements of the array
_VERSION_20w17a = 2529

# This version changes how biomes are stored to allow for biomes at different heights
# https://minecraft.wiki/w/Java_Edition_19w36a
_VERSION_19w36a = 2203

# This is the version where "The Flattening" (https://minecraft.gamepedia.com/Java_Edition_1.13/Flattening) happened
# where blocks went from numeric ids to namespaced ids (namespace:block_id)
_VERSION_17w47a = 1451


def _section_height_range(version: int | None) -> range:
    if version is not None and version > _VERSION_17w47a:
        return range(-4, 20)
    else:
        return range(16)


# dirty mixin to change q to Q
def _update_fmt(self, length):
    self.fmt = Struct(f">{length}Q")


nbt.TAG_Long_Array.update_fmt = _update_fmt


def bin_append(a, b, length=None):
    length = length or b.bit_length()
    return (a << length) | b


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


class Section:
    """
    Used for making own sections.

    This is where the blocks are actually stored, in a 16³ sized array.
    To save up some space, ``None`` is used instead of the air block object,
    and will be replaced with ``self.air`` when needed

    Attributes
    ----------
    y: :class:`int`
        Section's Y index
    blocks: List[:class:`Block`]
        1D list of blocks
    air: :class:`Block`
        An air block
    """

    __slots__ = ("y", "blocks", "air", "version", "data", "constructed", "biome")

    def __init__(self, data: nbt.TAG_COMPOUND, chunk_version, y=None):
        self.version = chunk_version
        self.blocks: list[Block] = [None] * 4096
        self.data = data
        if data is None:
            self.y = y
            self.constructed = True
            self.biome = None
        else:
            self.y = data["Y"].value
            self.constructed = False
            self.biome = None
        # Block that will be used when None
        self.air = Block("minecraft", "air")

    def read_data(self):
        """
        Decode section data
        """
        self.y = self.data["Y"].value

        try:
            block_states = _states_from_section(self.data)
        except KeyError:
            try:
                block_states = self.data["block_states"]
            except KeyError:
                print(f"Unreadable section {self.data}, resetting to all air")
                return
            block = block_states["palette"][0]["Name"].value
            if block == "minecraft:air":
                return
            else:
                self.blocks = [Block.from_name(block) for _ in range(4096)]
                return

        block_palette = _palette_from_section(self.data)

        # TODO: read Biome: can just read raw biome data and output this when saving if unchanged

        bits = max((len(block_palette) - 1).bit_length(), 4)

        stretches = self.version < _VERSION_20w17a

        data = block_states[0]
        data_len = 64
        state = 0

        bits_mask = 2**bits - 1

        for i in range(4096):
            if data_len < bits:
                state += 1
                new_data = block_states[state]

                if stretches:
                    leftover = data_len
                    data_len += 64

                    data = bin_append(new_data, data, leftover)
                else:
                    data = new_data
                    data_len = 64

            palette_id = data & bits_mask
            self.blocks[i] = Block.from_palette(block_palette[palette_id])

            data >>= bits
            data_len -= bits

    @staticmethod
    def inside(x: int, y: int, z: int) -> bool:
        """
        Check if X Y and Z are in range of 0-15

        Parameters
        ----------
        int x, y, z
            Coordinates
        """
        return x in range(16) and y in range(16) and z in range(16)

    def set_block(self, block: Block, x: int, y: int, z: int):
        """
        Sets the block at given coordinates

        Parameters
        ----------
        block
            Block to set
        int x, y, z
            Coordinates

        Raises
        ------
        anvil.OutOfBoundsCoordinates
            If coordinates are not in range of 0-15
        """
        if not self.inside(x, y, z):
            raise OutOfBoundsCoordinates("X Y and Z must be in range of 0-15")
        if not self.constructed:
            self.read_data()
            self.constructed = True
        index = y * 256 + z * 16 + x
        self.blocks[index] = block

    def get_block(self, x: int, y: int, z: int) -> Block:
        """
        Gets the block at given coordinates.

        Parameters
        ----------
        int x, y, z
            Coordinates

        Raises
        ------
        anvil.OutOfBoundsCoordinates
            If coordinates are not in range of 0-15
        """
        if not self.inside(x, y, z):
            raise OutOfBoundsCoordinates("X Y and Z must be in range of 0-15")
        if not self.constructed:
            self.read_data()
            self.constructed = True
        index = y * 256 + z * 16 + x
        return self.blocks[index] or self.air

    def set_biome(self, biome: Biome):
        self.biome = biome

    def palette(self) -> tuple[Block]:
        """
        Generates and returns a tuple of all the different blocks in the section
        The order can change as it uses sets, but should be fine when saving since
        it's only called once.
        """
        palette = set(self.blocks)
        if None in palette:
            palette.remove(None)
            palette.add(self.air)
        return tuple(palette)

    def blockstates(self, palette: tuple[Block] = None) -> array.array:
        """
        Returns a list of each block's index in the palette.

        This is used in the BlockStates tag of the section.

        Parameters
        ----------
        palette
            Section's palette. If not given will generate one.
        """
        palette = palette or self.palette()
        bits = max((len(palette) - 1).bit_length(), 4)
        states = array.array("Q")
        current = 0
        current_len = 0
        for block in self.blocks:
            index = palette.index(self.air) if block is None else palette.index(block)
            # If it's more than 64 bits then add to list and start over
            # with the remaining bits from last one
            if current_len + bits > 64:
                leftover = 64 - current_len
                states.append(bin_append(index & ((1 << leftover) - 1), current, length=current_len))
                current = index >> leftover
                current_len = bits - leftover
            else:
                current = bin_append(index, current, length=current_len)
                current_len += bits
        states.append(current)
        return states

    def save(self, new: bool = True) -> nbt.TAG_COMPOUND:
        """
        Saves the section to a TAG_Compound and is used inside the chunk tag, format depends on version
        This is missing the SkyLight tag, but minecraft still accepts it anyway
        """

        # TODO: support more versions when adding biomes?

        if not self.constructed:
            return self.data
        if new:
            return self.save_new()
        else:
            return self.save_old()

    def save_old(self) -> nbt.TAG_Compound:
        """
        Saves the section to a TAG_Compound and is used inside the chunk tag
        This is missing the SkyLight tag, but minecraft still accepts it anyway
        """
        root = nbt.TAG_Compound()
        root.tags.append(nbt.TAG_Byte(name="Y", value=self.y))

        palette = self.palette()
        nbt_pal = nbt.TAG_List(name="Palette", type=nbt.TAG_Compound)
        for block in palette:
            tag = nbt.TAG_Compound()
            tag.tags.append(nbt.TAG_String(name="Name", value=block.name()))
            if block.properties:
                properties = nbt.TAG_Compound()
                properties.name = "Properties"
                for key, value in block.properties.items():
                    if isinstance(value, str):
                        properties.tags.append(nbt.TAG_String(name=key, value=value))
                    elif isinstance(value, bool):
                        # booleans are a string saved as either 'true' or 'false'
                        properties.tags.append(nbt.TAG_String(name=key, value=str(value).lower()))
                    elif isinstance(value, int):
                        # ints also seem to be saved as a string
                        properties.tags.append(nbt.TAG_String(name=key, value=str(value)))
                    else:
                        # assume its a nbt tag and just append it
                        properties.tags.append(value)
                tag.tags.append(properties)
            nbt_pal.tags.append(tag)
        root.tags.append(nbt_pal)

        states = self.blockstates(palette=palette)
        bstates = nbt.TAG_Long_Array(name="BlockStates")
        bstates.value = states
        root.tags.append(bstates)

        return root

    def save_new(self) -> nbt.TAG_Compound:
        """
        Saves the section to a TAG_Compound and is used inside the chunk tag, using new format starting from 1.16
        """
        root = nbt.TAG_Compound()
        root.tags.append(nbt.TAG_Byte(name="Y", value=self.y))

        block_states = nbt.TAG_Compound(name="block_states")

        nbt_pal = nbt.TAG_List(name="palette", type=nbt.TAG_Compound)
        for block in self.palette():
            tag = nbt.TAG_Compound()
            tag.tags.append(nbt.TAG_String(name="Name", value=block.name()))
            if block.properties:
                properties = nbt.TAG_Compound()
                properties.name = "Properties"
                for key, value in block.properties.items():
                    if isinstance(value, str):
                        properties.tags.append(nbt.TAG_String(name=key, value=value))
                    elif isinstance(value, bool):
                        # booleans are a string saved as either 'true' or 'false'
                        properties.tags.append(nbt.TAG_String(name=key, value=str(value).lower()))
                    elif isinstance(value, int):
                        # ints also seem to be saved as a string
                        properties.tags.append(nbt.TAG_String(name=key, value=str(value)))
                    else:
                        # assume its a nbt tag and just append it
                        properties.tags.append(value)
                tag.tags.append(properties)
            nbt_pal.tags.append(tag)

        states = self.blockstates(palette=self.palette())
        bstates = nbt.TAG_Long_Array(name="data")
        bstates.value = states
        block_states.tags.append(nbt_pal)
        block_states.tags.append(bstates)

        nbt_biom = nbt.TAG_Compound(name="biomes")
        nbt_pal_biom = nbt.TAG_List(name="palette", type=nbt.TAG_String)
        # TODO: change when biome data is read
        if self.biome is not None:
            nbt_pal_biom.tags.append(nbt.TAG_String(value=self.biome.name()))
        else:
            nbt_pal_biom.tags.append(nbt.TAG_String(value="minecraft:plains"))
        nbt_biom.tags.append(nbt_pal_biom)

        root.tags.append(nbt_biom)
        root.tags.append(block_states)
        return root
