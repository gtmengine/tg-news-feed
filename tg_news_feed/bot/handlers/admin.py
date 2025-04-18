import logging
import re
import socket
import platform
import psutil
from typing import Optional
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from tg_news_feed.config import config
from tg_news_feed.storage.repo import Repository
from tg_news_feed.parser.fetcher import TelegramFetcher

logger = logging.getLogger(__name__)
router = Router()

# Track server start time for uptime calculation
SERVER_START_TIME = datetime.now()


def is_admin(user_id: int) -> bool:
    """Check if user is an admin."""
    return user_id in config.ADMIN_IDS


# Middleware to check admin status
@router.message(Command("stats"))
async def cmd_stats(message: Message, repo: Repository):
    """Handle /stats command - show statistics."""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав для использования этой команды.")
        return
    
    stats = repo.get_stats()
    
    await message.answer(
        "📊 *Статистика бота*\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"📝 Всего постов: {stats['posts']}\n"
        f"📡 Активных каналов: {stats['channels']}\n"
        f"❤️ Сохранённых постов: {stats['saved_posts']}",
        parse_mode="Markdown"
    )


@router.message(Command("server"))
async def cmd_server_info(message: Message):
    """Handle /server command - show server information."""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав для использования этой команды.")
        return
    
    # Get server information
    hostname = socket.gethostname()
    platform_info = platform.platform()
    uptime = datetime.now() - SERVER_START_TIME
    
    # Get system usage if psutil is available
    try:
        cpu_usage = f"{psutil.cpu_percent()}%"
        memory = psutil.virtual_memory()
        memory_usage = f"{memory.percent}% ({memory.used // 1024 // 1024}MB / {memory.total // 1024 // 1024}MB)"
        disk = psutil.disk_usage('/')
        disk_usage = f"{disk.percent}% ({disk.used // 1024 // 1024 // 1024}GB / {disk.total // 1024 // 1024 // 1024}GB)"
    except (ImportError, NameError):
        cpu_usage = "N/A"
        memory_usage = "N/A"
        disk_usage = "N/A"
    
    # Format uptime
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
    
    await message.answer(
        "🖥️ *Информация о сервере*\n\n"
        f"🏷️ Хост: `{hostname}`\n"
        f"💻 Платформа: `{platform_info}`\n"
        f"⏱️ Аптайм: `{uptime_str}`\n"
        f"🔄 CPU: `{cpu_usage}`\n"
        f"📊 Память: `{memory_usage}`\n"
        f"💾 Диск: `{disk_usage}`\n",
        parse_mode="Markdown"
    )


@router.message(Command("addchannel"))
async def cmd_add_channel(message: Message, repo: Repository, fetcher: TelegramFetcher):
    """Handle /addchannel command."""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав для использования этой команды.")
        return
    
    # Extract channel username from command
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "⚠️ Укажите @username канала.\n"
            "Пример: `/addchannel @example_channel`",
            parse_mode="Markdown"
        )
        return
    
    channel_username = args[1].strip()
    
    # Basic validation
    if not channel_username.startswith("@"):
        await message.answer(
            "⚠️ Username должен начинаться с символа @.\n"
            "Пример: `/addchannel @example_channel`",
            parse_mode="Markdown"
        )
        return
    
    # Remove @ for database storage but keep it for display
    clean_username = channel_username[1:]
    
    # Try to add channel
    try:
        await message.answer(f"🔄 Добавляю канал {channel_username}...")
        
        # Add to database
        channel = repo.add_channel(username=clean_username)
        
        if not channel:
            await message.answer(f"❌ Ошибка: не удалось добавить канал {channel_username}.")
            return
        
        # Immediate fetch of the channel's posts
        channel_dict = {
            'id': channel.id,
            'username': clean_username,
            'title': None
        }
        
        await message.answer(f"🔄 Получаю первоначальные посты из {channel_username}...")
        new_posts = await fetcher.fetch_channel_posts(channel_dict)
        
        await message.answer(
            f"✅ Канал {channel_username} успешно добавлен!\n\n"
            f"Получено первых постов: {new_posts}",
        )
        
    except Exception as e:
        logger.error(f"Error adding channel {channel_username}: {e}")
        await message.answer(
            f"❌ Произошла ошибка при добавлении канала:\n{str(e)}",
        )


@router.message(Command("suggestions"))
async def cmd_suggestions(message: Message, repo: Repository):
    """Handle /suggestions command - list channel suggestions."""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав для использования этой команды.")
        return
    
    suggestions = repo.get_suggestions()
    
    if not suggestions:
        await message.answer("Предложенных каналов пока нет.")
        return
    
    # Show up to 10 latest suggestions
    text = "📋 *Предложенные каналы:*\n\n"
    
    for i, suggestion in enumerate(suggestions[:10], 1):
        text += f"{i}. *{suggestion.channel_username}*\n"
        text += f"   От: `{suggestion.user_id}`\n"
        text += f"   Дата: {suggestion.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        if suggestion.comment:
            text += f"   Комментарий: _{suggestion.comment}_\n"
        text += "\n"
    
    if len(suggestions) > 10:
        text += f"\n_...и ещё {len(suggestions) - 10} предложений_"
    
    text += "\n\nЧтобы добавить канал, используйте команду:\n`/addchannel @username`"
    
    await message.answer(text, parse_mode="Markdown") 