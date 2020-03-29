import argparse
import json
import logging
import ssl
import sys
from urllib.parse import urlparse

import websockets

from . import names, __version__
from .unsee import UnseeImage
from .unsee_beta import download_album as download_album_beta

UNSEE_WEBSOCKET_URL = 'wss://ws.unsee.cc/{}/'


def find(f, seq):
    for item in seq:
        if f(item):
            return item
    return None


def get_album_id_from_url(album_url):
    url = urlparse(album_url)
    if url.netloc in ('', 'unsee.cc'):  # old unsee.cc
        path = [path for path in url.path.split('/') if len(path) > 0]
        if len(path) < 1:
            return None
        return path[0]
    elif url.netloc in ('app.unsee.cc', 'beta-app.unsee.cc'):  # new frontend or beta
        return url.fragment
    return None


def is_beta_album_id(album_id):
    return len(album_id) > 8


async def download_album(album_id, out_path='.', group_album=True):
    unsee_name = names.get_random()
    ws_params = '?album={}&name={}'.format(album_id, unsee_name)
    ssl_context = ssl.create_default_context()

    # Settings WS
    async with websockets.connect(UNSEE_WEBSOCKET_URL.format('settings') + ws_params, ssl=ssl_context) as ws_settings:
        await ws_settings.send('{}')
        data = await ws_settings.recv()

        settings = json.loads(data, encoding='utf-8')

        logging.info('[ws_settings] {}'.format(settings))

    images_info = []

    # PubSub WS
    async with websockets.connect(UNSEE_WEBSOCKET_URL.format('pubsub') + ws_params, ssl=ssl_context) as ws_pubsub:
        async for data in ws_pubsub:
            message = json.loads(data, encoding='utf-8')
            logging.debug('[ws_pubsub] Received message: {}'.format(message))

            if message['type'] == 'image':
                images_info.append(message)
                logging.info('[ws_pubsub] {}'.format(message))
            else:
                logging.debug('[ws_pubsub] Closing socket')
                await ws_pubsub.close()

    logging.info('Found {} images in album {}'.format(len(images_info), album_id))
    if 'title' in settings and len(settings['title']) > 0:
        print('Found album "{}" ({}) with {} images.'.format(settings['title'], album_id, len(images_info)))
    else:
        print('Found album {} with {} images.'.format(album_id, len(images_info)))

    # Imgpush WS
    async with websockets.connect(UNSEE_WEBSOCKET_URL.format('imgpush') + ws_params, ssl=ssl_context) as ws_imgpush:
        async for data in ws_imgpush:
            logging.debug('[ws_imgpush] received image (len: {})'.format(len(data)))

            # noinspection PyBroadException
            try:
                image = UnseeImage(album_id)
                image_path = image.write_file_from_blob(data, out_path=out_path, group_album=group_album)
                logging.debug('Wrote image {}'.format(image_path))

                image_info = find(lambda info: info['id'] == image.image_id, images_info)
                if image_info is not None:
                    images_info.remove(image_info)
            except:
                logging.warning('Failed writing image from album {}'.format(album_id))

            if len(images_info) <= 0:
                await ws_imgpush.close()


async def main():
    parser = argparse.ArgumentParser(description="unsee.cc downloader")
    parser.add_argument('--version', action='version', help="Print the version", version=f'%(prog)s {__version__}')
    parser.add_argument('-o', '--out', action="store", dest="out_dir", type=str, default=".",
                        help="Output directory")
    parser.add_argument('-v', '--verbose', action="store_const", dest="verbose", default=False, const=True,
                        help="Enable verbose output")
    parser.add_argument('-g', '--group', action="store_const", dest="group_album", default=False, const=True,
                        help="Group each album in its own directory")
    parser.add_argument('album_ids', action="store", nargs='+', help="unsee.cc album IDs to download")
    args = parser.parse_args(sys.argv[1:])

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    # Download images
    for album_id in args.album_ids:
        album_id = get_album_id_from_url(album_id)

        # noinspection PyBroadException
        try:
            print("Downloading album {:s}...".format(album_id))
            if is_beta_album_id(album_id):
                await download_album_beta(album_id, args.out_dir, group_album=args.group_album)
            else:
                await download_album(album_id, args.out_dir, group_album=args.group_album)
            logging.info("Download completed for album {}.".format(album_id))
        except Exception as ex:
            logging.error("Failed downloading album {}.".format(album_id), exc_info=ex)

    logging.shutdown()
