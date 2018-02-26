import zlib
from io import FileIO, BytesIO, SEEK_CUR

from util import common
from util.io_helper import IOHelper

FILE_MAGIC_OLD = 'Neople Image File'
FILE_MAGIC = 'Neople Img File'

FILE_VERSION_1 = 1
FILE_VERSION_2 = 2
FILE_VERSION_4 = 4
FILE_VERSION_5 = 5
FILE_VERSION_6 = 6

IMAGE_FORMAT_1555 = 14
IMAGE_FORMAT_4444 = 15
IMAGE_FORMAT_8888 = 16
IMAGE_FORMAT_LINK = 17
IMAGE_FORMAT_DXT_1 = 18
IMAGE_FORMAT_DXT_3 = 19
IMAGE_FORMAT_DXT_5 = 20

PIX_SIZE = {
    IMAGE_FORMAT_1555: 2,
    IMAGE_FORMAT_4444: 2,
    IMAGE_FORMAT_8888: 4,
    IMAGE_FORMAT_DXT_1: 2,
    IMAGE_FORMAT_DXT_3: 2,
    IMAGE_FORMAT_DXT_5: 4,
}

ZIP_TYPE_NONE = 5
ZIP_TYPE_ZLIB = 6
ZIP_TYPE_DDS_ZLIB = 7


class IMG:
    def __init__(self, io):
        self._io = io  # type: FileIO
        self._images = None  # type: dict
        self._dds_images = None  # type: dict
        self._version = None
        self._color_board = None  # type: dict
        self._color_boards = None  # type: dict

        self._open()

    def _open_images(self, count):
        io = self._io
        images = {}

        for i in range(count):
            image = {}

            [fmt] = IOHelper.read_struct(io, '<i')
            image['format'] = fmt

            if fmt == IMAGE_FORMAT_LINK:
                [link] = IOHelper.read_struct(io, '<i')
                image['link'] = link
            else:
                zip_type, w, h, size, x, y, mw, mh = IOHelper.read_struct(io, '<8i')

                # fix size to real size.
                if zip_type == ZIP_TYPE_NONE:
                    size = w * h * PIX_SIZE[fmt]

                image['zip_type'] = zip_type
                image['w'] = w
                image['h'] = h
                image['data'] = None
                image['size'] = size
                image['x'] = x
                image['y'] = y
                image['mw'] = mw
                image['mh'] = mh

                if self._version == FILE_VERSION_5:
                    keep_1, dds_index, lx, ly, rx, ry, keep_2 = IOHelper.read_struct(io, '<7i')
                    image['keep_1'] = keep_1
                    image['dds_index'] = dds_index
                    image['left'] = lx
                    image['top'] = ly
                    image['right'] = rx
                    image['bottom'] = ry
                    image['keep_2'] = keep_2
                elif self._version == FILE_VERSION_1:
                    images[i]['offset'] = io.tell()
                    io.seek(size, SEEK_CUR)

            images[i] = image

        return images

    def _open_color_board(self):
        io = self._io

        [count] = IOHelper.read_struct(io, 'i')

        colors = {}
        for i in range(count):
            colors[i] = IOHelper.read_struct(io, '<4B')

        return colors

    def _open_dds_images(self, dds_count):
        io = self._io

        dds_images = {}
        for i in range(dds_count):
            keep, fmt, index, data_size, raw_size, w, h = IOHelper.read_struct(io, '<7i')
            dds_images[i] = {
                'keep': keep,
                'format': fmt,
                'index': index,
                'data_size': data_size,
                'raw_size': raw_size,
                'w': w,
                'h': h,
            }

        return dds_images

    def _open(self):
        io = self._io
        io.seek(0)

        magic = IOHelper.read_ascii_string(io, 18)
        if magic == FILE_MAGIC or magic == FILE_MAGIC_OLD:
            if magic == FILE_MAGIC:
                # head_size without version,count...
                [head_size] = IOHelper.read_struct(io, 'i')
            else:
                # unknown.
                [unknown] = IOHelper.read_struct(io, 'h')

            # keep: 0
            [keep, version, img_count] = IOHelper.read_struct(io, '<3i')
            self._version = version

            if version == FILE_VERSION_4:
                # single color board.
                self._color_board = self._open_color_board()
            elif version == FILE_VERSION_5:
                # dds image.
                dds_count, file_size = IOHelper.read_struct(io, '<2i')
                self._color_board = self._open_color_board()
                self._dds_images = self._open_dds_images(dds_count)
            elif version == FILE_VERSION_6:
                # multiple color board.
                color_boards = {}

                [color_board_count] = IOHelper.read_struct(io, 'i')
                for i in range(color_board_count):
                    color_boards[i] = self._open_color_board()

                self._color_boards = color_boards

            images = self._open_images(img_count)
            self._images = images

            # count image offset.
            if version != FILE_VERSION_1:
                # behind header.
                offset = io.tell()
                if version == FILE_VERSION_5:
                    dds_images = self._dds_images
                    for i in dds_images:
                        dds_image = dds_images[i]
                        dds_image['offset'] = offset
                        offset += dds_image['data_size']
                else:
                    for i in images:
                        image = images[i]
                        if image['format'] != IMAGE_FORMAT_LINK:
                            image['offset'] = offset
                            offset += image['size']
        else:
            raise Exception('Not NPK File.')

    def load_image(self, index):
        io = self._io
        image = self._images[index]

        if image['format'] == IMAGE_FORMAT_LINK:
            return self.load_image(image['link'])

        if image['data'] is not None:
            return image['data']

        if self._version == FILE_VERSION_5:
            dds_image = self._dds_images[image['dds_index']]
            data = IOHelper.read_range(io, dds_image['offset'], dds_image['data_size'])
        else:
            data = IOHelper.read_range(io, image['offset'], image['size'])

        if image['zip_type'] == ZIP_TYPE_ZLIB or image['zip_type'] == ZIP_TYPE_DDS_ZLIB:
            data = zlib.decompress(data)
        elif image['zip_type'] != ZIP_TYPE_NONE:
            raise Exception('Unknown Zip Type.', image['zip_type'])

        image['data'] = data
        return data

    def _load_image_all(self):
        images = self._images

        for i in images:
            self.load_image(i)

        return images

    def _save_count_head_size(self):
        images = self._images
        dds_images = self._dds_images
        color_board = self._color_board
        color_boards = self._color_boards
        version = self._version

        head_size = 0

        is_ver5 = version == FILE_VERSION_5

        if version == FILE_VERSION_4 or is_ver5:
            # color count.
            head_size += 4
            # colors size.
            head_size += len(color_board) * 4

        if is_ver5:
            # dds_count, img_size
            head_size += 8
            # keep, format, index, data_size, raw_size, w, h
            head_size += len(dds_images) * 28

        if version == FILE_VERSION_6:
            # color_boards_count
            head_size += 4
            for color_board_v6 in color_boards.values():
                # color count.
                head_size += 4
                # colors size.
                head_size += len(color_board_v6) * 4

        for image in images.values():
            # format
            head_size += 4
            if image['format'] == IMAGE_FORMAT_LINK:
                # link
                head_size += 4
            else:
                # zip_type, w, h, data, size, x, y, mw, mh
                head_size += 36
                if is_ver5:
                    # keep_1, dds_index, left, top, right, bottom, keep_2
                    head_size += 28

        return head_size

    def save(self, io=None):
        images = self._load_image_all()
        color_board = self._color_board
        color_boards = self._color_boards
        dds_images = self._dds_images
        version = self._version

        if io is None:
            io = self._io

        io.seek(0)
        io.truncate()

        with BytesIO() as io_head:
            if version == FILE_VERSION_1:
                IOHelper.write_ascii_string(io_head, FILE_MAGIC_OLD)
                # TODO: unknown, now be zero.
                IOHelper.write_struct(io_head, 'h', 0)
            else:
                IOHelper.write_ascii_string(io_head, FILE_MAGIC)
                IOHelper.write_struct(io_head, 'i', self._save_count_head_size())

            # keep, version, img_count
            IOHelper.write_struct(io_head, '<3i', 0, version, len(images))

            is_ver5 = version == FILE_VERSION_5

            if version == FILE_VERSION_4 or is_ver5:
                # color_count
                IOHelper.write_struct(io_head, 'i', len(color_board))
                for color in color_board.values():
                    # color
                    IOHelper.write_struct(io_head, '<4B', *color)

            if is_ver5:
                # dds_count, file_size
                # TODO: file_size, now be zero.
                IOHelper.write_struct(io_head, '<2i', len(dds_images), 0)
                for dds_image in dds_images.values():
                    IOHelper.write_struct(io_head, '<7i', dds_image['keep'], dds_image['format'], dds_image['index'],
                                          dds_image['data_size'], dds_image['raw_size'], dds_image['w'], dds_image['h'])

            if version == FILE_VERSION_6:
                # color_board count.
                IOHelper.write_struct(io_head, 'i', len(color_boards))
                for color_board_v6 in color_boards:
                    # color_count
                    IOHelper.write_struct(io_head, 'i', len(color_board_v6))
                    for color in color_board_v6.values():
                        # color
                        IOHelper.write_struct(io_head, '<4B', *color)

            head_data = IOHelper.read_range(io_head)

        io.write(head_data)

        # TODO: write image data.

    def build(self, index, color_board_index=0):
        data = self.load_image(index)
        image = self._images[index]

        if self._version == FILE_VERSION_1 or self._version == FILE_VERSION_2:
            data = IMG._nximg_to_raw(data, image['format'])
        elif self._version == FILE_VERSION_4:
            data = IMG._indexes_to_raw(data, self._color_board)
        elif self._version == FILE_VERSION_5:
            data = common.dds_to_png(data)
        elif self._version == FILE_VERSION_6:
            data = IMG._indexes_to_raw(data, self._color_boards[color_board_index])
        else:
            raise Exception('Unknown IMG Version.', self._version)

        if self._version == FILE_VERSION_1 or self._version == FILE_VERSION_2 or self._version == FILE_VERSION_4 or self._version == FILE_VERSION_6:
            data = common.raw_to_png(data, image['w'], image['h'])

        return data

    def get_info(self, index):
        image = self._images[index]  # type: dict

        info = {}
        for k, v in image.items():
            if k != 'data' and 'keep' not in k:
                info[k] = v

        dds_id = info.get('dds_index')
        if dds_id is not None:
            info_dds_image = {}

            dds_image = self._dds_images[dds_id]
            for k, v in dds_image.items():
                if 'keep' not in k:
                    info_dds_image[k] = v

            info['dds_image'] = info_dds_image

        return info

    @staticmethod
    def _indexes_to_raw(data, color_board):
        with BytesIO(data) as io_indexes:
            with BytesIO() as io_raw:
                temp = IOHelper.read_struct(io_indexes, '<B', False)
                while temp is not None:
                    [index] = temp
                    IOHelper.write_struct(io_raw, '<4B', *color_board[index])
                    temp = IOHelper.read_struct(io_indexes, '<B', False)
                data_raw = IOHelper.read_range(io_raw)

        return data_raw

    @staticmethod
    def _nximg_to_raw(data, image_format):
        data_raw = bytes()

        with BytesIO(data) as io_nximg:
            with BytesIO() as io_raw:
                if image_format == IMAGE_FORMAT_1555:
                    temp = IOHelper.read_struct(io_nximg, '<h', False)
                    while temp is not None:
                        [color] = temp
                        b = (color & 31) << 3
                        g = (color & 992) >> 2
                        r = (color & 31744) >> 7
                        a = (color & 32768)
                        if a != 0:
                            a = 255
                        IOHelper.write_struct(io_raw, '<4B', r, g, b, a)

                        temp = IOHelper.read_struct(io_nximg, '<h', False)
                elif image_format == IMAGE_FORMAT_4444:
                    temp = IOHelper.read_struct(io_nximg, '<2B', False)
                    while temp is not None:
                        [b1, b2] = temp
                        b = (b1 & 15) << 4
                        g = b1 & 240
                        r = (b2 & 15) << 4
                        a = b2 & 240
                        IOHelper.write_struct(io_raw, '<4B', r, g, b, a)

                        temp = IOHelper.read_struct(io_nximg, '<2B', False)
                elif image_format == IMAGE_FORMAT_8888:
                    temp = IOHelper.read_struct(io_nximg, '<4B', False)
                    while temp is not None:
                        [b, g, r, a] = temp
                        IOHelper.write_struct(io_raw, '<4B', r, g, b, a)

                        temp = IOHelper.read_struct(io_nximg, '<4B', False)
                else:
                    raise Exception('Unsupport Image Format.', image_format)

                data_raw = IOHelper.read_range(io_raw)

        return data_raw

    @property
    def color_board(self):
        return self._color_board

    @property
    def color_boards(self):
        return self._color_boards

    @property
    def images(self):
        if self._images is not None:
            return list(self._images.keys())

    @property
    def dds_images(self):
        if self._dds_images is not None:
            return list(self._dds_images.keys())

    @property
    def version(self):
        return self._version
