from asyncio import Event, sleep

from bot import (
    LOGGER,
    queued_dl,
    queued_up,
    config_dict,
    non_queued_dl,
    non_queued_up,
    queue_dict_lock,
)
from bot.helper.ext_utils.bot_utils import sync_to_async, get_telegraph_list
from bot.helper.ext_utils.files_utils import get_base_name
from bot.helper.ext_utils.links_utils import is_gdrive_id
from bot.helper.mirror_leech_utils.gdrive_utils.search import gdSearch


async def limit_checker(
        listener,
        is_Torrent=False,
        is_Mega=False,
        is_DriveLink=False,
        is_Rclone=False,
    ):
    try:
        if await isAdmin(listener.message):
            return
    except Exception as e:
        LOGGER.error(f"Error while checking if the user is Admin: {e}")

    GB = 1024 ** 3
    limit_exceeded = ""

async def stop_duplicate_check(listener):
    if (
        isinstance(listener.upDest, int)
        or listener.is_leech
        or listener.select
        or not is_gdrive_id(listener.upDest)
        or (listener.upDest.startswith("mtp:") and listener.stopDuplicate)
        or not listener.stopDuplicate
        or listener.same_dir
    ):
        return False, None

    name = listener.name
    LOGGER.info(f"Checking File/Folder if already in Drive: {name}")

    if listener.compress:
        name = f"{name}.7z"
    elif listener.extract:
        try:
            name = get_base_name(name)
        except Exception:
            name = None

    if name is not None:
        telegraph_content, contents_no = await sync_to_async(
            gdSearch(stopDup=True, noMulti=listener.isClone).drive_list,
            name,
            listener.upDest,
            listener.userId,
        )
        if telegraph_content:
            msg = f"File/Folder is already available in Drive.\nHere are {contents_no} list results:"
            button = await get_telegraph_list(telegraph_content)
            return msg, button

    return False, None

async def check_limits_size(listener, size, playlist=False, play_count=False):
    msgerr = None
    max_pyt, megadl, torddl, zuzdl, leechdl = (config_dict["MAX_YTPLAYLIST"], config_dict["MEGA_LIMIT"], config_dict["TORRENT_DIRECT_LIMIT"],
config_dict["ZIP_UNZIP_LIMIT"], config_dict["LEECH_LIMIT"])

    arch = any([listener.compress, listener.is_Leech, listener.extract])
    if torddl and not arch and size >= torddl * 1024**3:
        msgerr = f"Torrent/direct limit is {torddl}GB"
    elif zuzdl and any([listener.compress, listener.extract]) and size >= zuzdl * 1024**3:
        msgerr = f"Zip/Unzip limit is {zuzdl}GB"
    elif leechdl and listener.is_Leech and size >= leechdl * 1024**3:
        msgerr = f"Leech limit is {leechdl}GB"
    if is_mega_link(listener.link) and megadl and size >= megadl * 1024**3:
        msgerr = f"Mega limit is {megadl}GB"
    if max_pyt and playlist and (play_count > max_pyt):
        msgerr = f"Only {max_pyt} playlist allowed. Current playlist is {play_count}."
    return msgerr

async def check_running_tasks(listener, state="dl"):
    all_limit = config_dict["QUEUE_ALL"]
    state_limit = (
        config_dict["QUEUE_DOWNLOAD"]
        if state == "dl"
        else config_dict["QUEUE_UPLOAD"]
    )
    event = None
    is_over_limit = False
    async with queue_dict_lock:
        if state == "up" and listener.mid in non_queued_dl:
            non_queued_dl.remove(listener.mid)
        if all_limit or state_limit:
            dl_count = len(non_queued_dl)
            up_count = len(non_queued_up)
            t_count = dl_count if state == "dl" else up_count
            is_over_limit = (
                all_limit
                and dl_count + up_count >= all_limit
                and (not state_limit or t_count >= state_limit)
            ) or (state_limit and t_count >= state_limit)
            if is_over_limit:
                event = Event()
                if state == "dl":
                    queued_dl[listener.mid] = event
                else:
                    queued_up[listener.mid] = event
        if not is_over_limit:
            if state == "up":
                non_queued_up.add(listener.mid)
            else:
                non_queued_dl.add(listener.mid)

    return is_over_limit, event


async def start_dl_from_queued(mid: int):
    queued_dl[mid].set()
    del queued_dl[mid]
    await sleep(0.7)


async def start_up_from_queued(mid: int):
    queued_up[mid].set()
    del queued_up[mid]
    await sleep(0.7)


async def start_from_queued():
    if all_limit := config_dict["QUEUE_ALL"]:
        dl_limit = config_dict["QUEUE_DOWNLOAD"]
        up_limit = config_dict["QUEUE_UPLOAD"]
        async with queue_dict_lock:
            dl = len(non_queued_dl)
            up = len(non_queued_up)
            all_ = dl + up
            if all_ < all_limit:
                f_tasks = all_limit - all_
                if queued_up and (not up_limit or up < up_limit):
                    for index, mid in enumerate(list(queued_up.keys()), start=1):
                        f_tasks = all_limit - all_
                        await start_up_from_queued(mid)
                        f_tasks -= 1
                        if f_tasks == 0 or (up_limit and index >= up_limit - up):
                            break
                if queued_dl and (not dl_limit or dl < dl_limit) and f_tasks != 0:
                    for index, mid in enumerate(list(queued_dl.keys()), start=1):
                        await start_dl_from_queued(mid)
                        if (dl_limit and index >= dl_limit - dl) or index == f_tasks:
                            break
        return

    if up_limit := config_dict["QUEUE_UPLOAD"]:
        async with queue_dict_lock:
            up = len(non_queued_up)
            if queued_up and up < up_limit:
                f_tasks = up_limit - up
                for index, mid in enumerate(list(queued_up.keys()), start=1):
                    await start_up_from_queued(mid)
                    if index == f_tasks:
                        break
    else:
        async with queue_dict_lock:
            if queued_up:
                for mid in list(queued_up.keys()):
                    await start_up_from_queued(mid)

    if dl_limit := config_dict["QUEUE_DOWNLOAD"]:
        async with queue_dict_lock:
            dl = len(non_queued_dl)
            if queued_dl and dl < dl_limit:
                f_tasks = dl_limit - dl
                for index, mid in enumerate(list(queued_dl.keys()), start=1):
                    await start_dl_from_queued(mid)
                    if index == f_tasks:
                        break
    else:
        async with queue_dict_lock:
            if queued_dl:
                for mid in list(queued_dl.keys()):
                    await start_dl_from_queued(mid)
