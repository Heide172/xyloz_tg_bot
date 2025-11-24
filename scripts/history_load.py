# !/usr/bin/env python3
"""
Скрипт для импорта истории Telegram чатов в базу данных
Поддерживает все типы медиа, множественный импорт и прогресс-бар
"""

import asyncio
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_PATH = PROJECT_ROOT / '.env'

# Добавляем корневую директорию в путь
sys.path.insert(0, str(PROJECT_ROOT))

# Загружаем .env файл
from dotenv import load_dotenv
load_dotenv(dotenv_path=ENV_PATH, verbose=True)# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


try:
    from pyrogram import Client
    from pyrogram.types import Message as PyrogramMessage
    from sqlalchemy.orm import Session
    from tqdm import tqdm
    import emoji  # ✅ Добавьте эту строку, если её нет
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("\n📦 Установите зависимости:")
    print("   pip install pyrogram tgcrypto tqdm emoji")
    sys.exit(1)

from common.db.db import SessionLocal
from common.models.message import Message
from common.models.user import User

# ============================================================================
# КОНФИГУРАЦИЯ - ИЗМЕНИТЕ ЭТИ ЗНАЧЕНИЯ
# ============================================================================

# Получите на https://my.telegram.org
TG_API_ID = os.getenv('TG_API_ID', 'YOUR_API_ID')
TG_API_HASH = os.getenv('TG_API_HASH', 'YOUR_API_HASH')
TG_PHONE = os.getenv('TG_PHONE', '+1234567890')
TG_SESSION_NAME = os.getenv('TG_SESSION_NAME', 'my_telegram_session')

# Настройки импорта
BATCH_SIZE = 100  # Количество сообщений для коммита


# ============================================================================
# ОСНОВНОЙ КОД
# ============================================================================

class ChatHistoryImporter:
    """Класс для импорта истории чатов"""

    def __init__(self):
        """Инициализация импортера"""
        self.client = Client(
            TG_SESSION_NAME,
            api_id=TG_API_ID,
            api_hash=TG_API_HASH,
            phone_number=TG_PHONE
        )
        self.db: Optional[Session] = None
        self.stats = {
            'total': 0,
            'imported': 0,
            'skipped': 0,
            'errors': 0
        }

    async def resolve_peer(self, chat_id: str) -> tuple:
        """
        Пытается разрешить peer для групповых чатов
        Возвращает (chat_object, numeric_id) или (None, None)
        """
        print(f"🔍 Поиск группы с ID: {chat_id}")

        # Сначала ищем группу в диалогах
        try:
            async for dialog in self.client.get_dialogs():
                if str(dialog.chat.id) == str(chat_id):
                    print(f"✅ Группа найдена в диалогах: {dialog.chat.title}")
                    return dialog.chat, dialog.chat.id
        except Exception as e:
            print(f"⚠️  Ошибка при поиске в диалогах: {e}")

        # Пробуем прямое получение
        try:
            chat = await self.client.get_chat(chat_id)
            print(f"✅ Группа получена напрямую: {getattr(chat, 'title', 'Unknown')}")
            return chat, chat.id
        except Exception as e:
            print(f"⚠️  Не удалось получить группу напрямую: {e}")

        # Пробуем разные форматы ID для супергрупп
        if str(chat_id).lstrip('-').isdigit():
            chat_id_num = int(chat_id)

            # Для супергрупп Telegram использует разные форматы
            variants = []

            if str(chat_id).startswith('-100'):
                # Это уже полный ID супергруппы
                base_id = str(chat_id)[4:]  # Убираем -100
                variants = [
                    int(chat_id),
                    int(base_id),
                    int(f"-{base_id}"),
                ]
            else:
                # Пробуем добавить -100 префикс
                variants = [
                    chat_id_num,
                    int(f"-100{abs(chat_id_num)}"),
                    -abs(chat_id_num),
                ]

            print(f"🔄 Пробую варианты ID: {variants}")

            for variant in variants:
                try:
                    # Сначала проверяем в диалогах
                    async for dialog in self.client.get_dialogs():
                        if dialog.chat.id == variant:
                            print(f"✅ Группа найдена с ID: {variant}")
                            return dialog.chat, dialog.chat.id

                    # Затем пробуем прямое получение
                    chat = await self.client.get_chat(variant)
                    print(f"✅ Группа получена с ID: {variant}")
                    return chat, chat.id
                except Exception as e:
                    continue

        return None, None

    async def list_available_chats(self, groups_only: bool = True):
        """Выводит список доступных чатов (по умолчанию только группы)"""
        print("\n📋 Получаем список ваших чатов...")
        print("-" * 80)

        dialogs_count = 0
        groups_count = 0

        async for dialog in self.client.get_dialogs():
            chat = dialog.chat

            # Определяем тип чата
            is_group = False
            chat_type_str = str(getattr(chat, 'type', '')).lower()

            if 'group' in chat_type_str or 'supergroup' in chat_type_str:
                is_group = True
                chat_type = "👥 Группа"
                groups_count += 1
            elif 'channel' in chat_type_str:
                chat_type = "📢 Канал"
                if not groups_only:
                    is_group = True  # Показываем каналы если не только группы
            elif 'private' in chat_type_str:
                chat_type = "👤 Личный чат"
            elif 'bot' in chat_type_str:
                chat_type = "🤖 Бот"
            else:
                chat_type = "❓ Неизвестно"

            # Показываем только группы если groups_only=True
            if groups_only and not is_group:
                continue

            dialogs_count += 1

            chat_name = getattr(chat, 'title', None) or getattr(chat, 'first_name', 'Unknown')
            username = getattr(chat, 'username', None)
            members_count = getattr(chat, 'members_count', None)

            print(f"{chat_type:<15} | {chat_name[:35]:<35}")
            print(f"   🆔 ID: {chat.id}")
            if username:
                print(f"   🔗 @{username}")
            if members_count:
                print(f"   👥 Участников: {members_count}")
            print()

        if groups_only:
            print(f"📊 Найдено групп: {groups_count}")
        else:
            print(f"📊 Всего чатов: {dialogs_count}")
        print("-" * 80)

    @staticmethod
    def get_message_type(message: PyrogramMessage) -> str:
        """Определяет тип сообщения"""
        if message.photo:
            return 'photo'
        elif message.video:
            return 'video'
        elif message.audio:
            return 'audio'
        elif message.voice:
            return 'voice'
        elif message.document:
            return 'document'
        elif message.sticker:
            return 'sticker'
        elif message.animation:
            return 'animation'
        elif message.video_note:
            return 'video_note'
        elif message.location:
            return 'location'
        elif message.contact:
            return 'contact'
        elif message.poll:
            return 'poll'
        elif message.text:
            return 'text'
        else:
            return 'other'

    @staticmethod
    def extract_media_info(message: PyrogramMessage) -> dict:
        """Извлекает информацию о медиа из сообщения"""
        media_info = {
            'file_id': None,
            'file_unique_id': None,
            'file_name': None,
            'mime_type': None,
            'file_size': None,
            'has_media': False
        }

        media = None
        if message.photo:
            media = message.photo
            media_info['file_name'] = f"photo_{message.id}.jpg"
        elif message.video:
            media = message.video
            media_info['file_name'] = getattr(message.video, 'file_name', f"video_{message.id}.mp4")
            media_info['mime_type'] = getattr(message.video, 'mime_type', None)
        elif message.audio:
            media = message.audio
            media_info['file_name'] = getattr(message.audio, 'file_name', f"audio_{message.id}.mp3")
            media_info['mime_type'] = getattr(message.audio, 'mime_type', None)
        elif message.voice:
            media = message.voice
            media_info['file_name'] = f"voice_{message.id}.ogg"
            media_info['mime_type'] = getattr(message.voice, 'mime_type', 'audio/ogg')
        elif message.document:
            media = message.document
            media_info['file_name'] = getattr(message.document, 'file_name', f"document_{message.id}")
            media_info['mime_type'] = getattr(message.document, 'mime_type', None)
        elif message.sticker:
            media = message.sticker
            media_info['file_name'] = f"sticker_{message.id}.webp"
        elif message.animation:
            media = message.animation
            media_info['file_name'] = getattr(message.animation, 'file_name', f"animation_{message.id}.gif")
            media_info['mime_type'] = getattr(message.animation, 'mime_type', None)
        elif message.video_note:
            media = message.video_note
            media_info['file_name'] = f"video_note_{message.id}.mp4"

        if media:
            media_info['has_media'] = True
            media_info['file_id'] = getattr(media, 'file_id', None)
            media_info['file_unique_id'] = getattr(media, 'file_unique_id', None)
            media_info['file_size'] = getattr(media, 'file_size', None)

        return media_info

    def get_or_create_user(self, message: PyrogramMessage) -> Optional[User]:
        """Получает или создает пользователя"""
        if not message.from_user:
            return None

        user = self.db.query(User).filter(User.tg_id == message.from_user.id).first()

        if not user:
            fullname = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
            user = User(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                fullname=fullname or message.from_user.username or f"User{message.from_user.id}"
            )
            self.db.add(user)
            self.db.flush()

        return user



    async def import_message(self, message: PyrogramMessage, chat_id: int) -> bool:
        """Импортирует одно сообщение из группы"""
        try:
            # Проверяем, существует ли уже сообщение
            existing = self.db.query(Message).filter(
                Message.telegram_message_id == message.id,
                Message.chat_id == chat_id
            ).first()

            if existing:
                self.stats['skipped'] += 1
                return False

            # Получаем или создаем пользователя (в группах from_user может быть None)
            user = None
            if message.from_user:
                user = self.get_or_create_user(message)

            # Определяем тип сообщения
            message_type = self.get_message_type(message)

            # Извлекаем медиа информацию
            media_info = self.extract_media_info(message)

            # Получаем ID источника форварда
            forward_from_id = None
            if message.forward_from:
                forward_from_id = str(message.forward_from.id)
            elif message.forward_from_chat:
                forward_from_id = str(message.forward_from_chat.id)

            # ✅ Получаем reply_to (ID сообщения, на которое отвечают)
            reply_to = None
            if message.reply_to_message:
                reply_to = message.reply_to_message.id

            # ✅ Получаем sticker file_id
            sticker = None
            if message.sticker:
                sticker = message.sticker.file_id

            # ✅ Извлекаем emojis из текста
            emojis = None
            text_content = message.text or message.caption or ''
            if text_content:
                import emoji as emoji_lib
                emojis = "".join([e for e in text_content if emoji_lib.is_emoji(e)])

            # Создаем запись сообщения с правильными полями
            new_message = Message(
                message_id=message.id,  # ✅ Заполняем оба поля
                telegram_message_id=message.id,  # ✅ Дублируем для совместимости
                user_id=user.id if user else None,
                chat_id=chat_id,
                text=text_content,
                caption=message.caption or '',
                message_type=message_type,

                # ✅ Поля из message_service.py
                emojis=emojis,
                sticker=sticker,
                media=media_info.get('file_id') if message_type in ['photo', 'video', 'audio'] else None,
                reply_to=reply_to,

                # Медиа информация (для истории)
                file_id=media_info.get('file_id'),
                file_unique_id=media_info.get('file_unique_id'),
                file_name=media_info.get('file_name'),
                mime_type=media_info.get('mime_type'),
                file_size=media_info.get('file_size'),
                has_media=media_info.get('has_media', False),

                # Информация о форварде
                is_forwarded=bool(message.forward_date),
                forward_from=forward_from_id,

                # Временные метки
                created_at=message.date if message.date else datetime.utcnow(),
                edited_at=message.edit_date,
            )

            self.db.add(new_message)
            self.stats['imported'] += 1

            return True

        except Exception as e:
            self.stats['errors'] += 1
            print(f"\n❌ Ошибка при импорте сообщения {message.id}: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def import_chat(self, chat_id: str, limit: Optional[int] = None) -> dict:
        """Импортирует историю одной группы"""
        print(f"\n📥 Начинаем импорт группы: {chat_id}")

        try:
            # Пытаемся разрешить peer
            chat, numeric_chat_id = await self.resolve_peer(chat_id)

            if chat is None:
                print(f"\n❌ Не удалось найти группу: {chat_id}")
                print("\n💡 Возможные причины:")
                print("   1. Вы не являетесь участником этой группы")
                print("   2. Неверный ID группы")
                print("   3. Группа не существует или была удалена")
                print("   4. У вас нет прав на просмотр истории")
                print("\n💡 Что делать:")
                print("   - Введите 'list' чтобы увидеть список ВАШИХ групп")
                print("   - Убедитесь что вы участник группы")
                print("   - Используйте @username группы если он есть")
                print("   - Попробуйте сначала написать в группу, затем запустите импорт")

                return {
                    'chat_id': chat_id,
                    'success': False,
                    'error': 'PEER_ID_INVALID - группа не найдена'
                }

            chat_name = getattr(chat, 'title', 'Unknown Group')
            print(f"📝 Группа: {chat_name}")
            print(f"🆔 ID: {numeric_chat_id}")

            # Проверяем права доступа
            members_count = getattr(chat, 'members_count', 'неизвестно')
            print(f"👥 Участников: {members_count}")

            # Получаем примерное количество сообщений
            message_count = limit if limit else "все доступные"
            print(f"📊 Будет импортировано: {message_count}")

            # Создаем прогресс-бар
            pbar = tqdm(
                total=limit,
                desc=f"💬 {chat_name[:20]}",
                unit="msg",
                colour="green"
            )

            batch_count = 0
            message_counter = 0

            async for message in self.client.get_chat_history(numeric_chat_id, limit=limit):
                self.stats['total'] += 1
                message_counter += 1

                # Пробуем импортировать сообщение
                success = await self.import_message(message, numeric_chat_id)

                # Если была ошибка, откатываем транзакцию для продолжения работы
                if not success and self.stats['errors'] > 0:
                    self.db.rollback()

                batch_count += 1
                pbar.update(1)

                # Коммитим батчами
                if batch_count >= BATCH_SIZE:
                    try:
                        self.db.commit()
                    except Exception as e:
                        print(f"\n⚠️  Ошибка при коммите: {e}")
                        self.db.rollback()
                    batch_count = 0

            # Финальный коммит
            if batch_count > 0:
                try:
                    self.db.commit()
                except Exception as e:
                    print(f"\n⚠️  Ошибка при финальном коммите: {e}")
                    self.db.rollback()

            pbar.close()

            return {
                'chat_id': chat_id,
                'chat_name': chat_name,
                'success': True,
                'stats': self.stats.copy()
            }

        except Exception as e:
            self.db.rollback()
            print(f"\n❌ Ошибка при импорте группы {chat_id}: {e}")
            import traceback
            traceback.print_exc()
            return {
                'chat_id': chat_id,
                'success': False,
                'error': str(e)
            }

    async def import_multiple_chats(self, chat_ids: List[str], limit: Optional[int] = None):
        """Импортирует историю из нескольких чатов"""
        print(f"\n🚀 Начинаем импорт из {len(chat_ids)} чатов")
        print("=" * 70)

        results = []
        total_imported = 0
        total_skipped = 0
        total_errors = 0

        for i, chat_id in enumerate(chat_ids, 1):
            print(f"\n[{i}/{len(chat_ids)}] Обработка чата...")

            # Сбрасываем статистику для каждого чата
            self.stats = {
                'total': 0,
                'imported': 0,
                'skipped': 0,
                'errors': 0
            }

            result = await self.import_chat(chat_id, limit)
            results.append(result)

            if result['success']:
                print(f"\n✅ Чат '{result.get('chat_name', chat_id)}' завершен:")
                print(f"   📥 Импортировано: {self.stats['imported']}")
                print(f"   ⏭️  Пропущено: {self.stats['skipped']}")
                print(f"   ❌ Ошибок: {self.stats['errors']}")

                total_imported += self.stats['imported']
                total_skipped += self.stats['skipped']
                total_errors += self.stats['errors']
            else:
                print(f"\n❌ Чат {chat_id} не удалось обработать: {result.get('error')}")

            print("-" * 70)

        # Итоговая статистика
        print("\n" + "=" * 70)
        print("📊 ИТОГОВАЯ СТАТИСТИКА:")
        print("=" * 70)
        print(f"   Всего чатов: {len(chat_ids)}")
        print(f"   Успешно: {sum(1 for r in results if r['success'])}")
        print(f"   С ошибками: {sum(1 for r in results if not r['success'])}")
        print(f"   📥 Всего импортировано: {total_imported}")
        print(f"   ⏭️  Всего пропущено: {total_skipped}")
        print(f"   ❌ Всего ошибок: {total_errors}")
        print("=" * 70)

        return results

    async def run(self, chat_ids: List[str], limit: Optional[int] = None):
        """Основной метод запуска импорта"""
        self.db = SessionLocal()

        try:
            print("\n🔄 Подключение к Telegram...")
            await self.client.start()
            print("✅ Клиент Pyrogram запущен\n")

            if len(chat_ids) == 1:
                await self.import_chat(chat_ids[0], limit)

                # Итоговая статистика для одного чата
                print("\n" + "=" * 70)
                print("🎉 ИМПОРТ ЗАВЕРШЕН!")
                print("=" * 70)
                print(f"   📥 Импортировано: {self.stats['imported']}")
                print(f"   ⏭️  Пропущено: {self.stats['skipped']}")
                print(f"   ❌ Ошибок: {self.stats['errors']}")
                print("=" * 70)
            else:
                await self.import_multiple_chats(chat_ids, limit)

        except Exception as e:
            print(f"\n❌ Критическая ошибка: {e}")
            self.db.rollback()
            raise
        finally:
            self.db.close()
            await self.client.stop()
            print("\n👋 Клиент остановлен")


# ============================================================================
# ИНТЕРФЕЙС КОМАНДНОЙ СТРОКИ
# ============================================================================

def print_header():
    """Выводит заголовок программы"""
    print("\n" + "=" * 70)
    print("📨 ИМПОРТ ИСТОРИИ TELEGRAM ЧАТОВ В БАЗУ ДАННЫХ")
    print("=" * 70)


def print_help():
    """Выводит справку"""
    print("""
📖 СПРАВКА:

Как использовать:
    python scripts/import_chat_history.py

Параметры в .env:
    TG_API_ID       - API ID из https://my.telegram.org
    TG_API_HASH     - API Hash из https://my.telegram.org
    TG_PHONE        - Номер телефона в формате +1234567890

Примеры ввода чатов:
    @channelname                    - Публичный канал/группа
    -1001234567890                  - ID группы/канала
    @user1, @channel2, -1001234567  - Несколько чатов

Типы поддерживаемых сообщений:
    ✅ Текст, Фото, Видео, Аудио, Документы
    ✅ Голосовые, Стикеры, GIF, Видео-заметки
    ✅ Геолокация, Контакты, Опросы
    """)


async def main():
    """Интерактивный режим"""
    print_header()

    # Проверяем конфигурацию
    if TG_API_ID == 'YOUR_API_ID' or TG_API_HASH == 'YOUR_API_HASH':
        print("\n⚠️  ВНИМАНИЕ: Настройте TG_API_ID и TG_API_HASH!")
        print("   Получите их на https://my.telegram.org")
        print("   Добавьте в .env файл или измените в начале скрипта")
        print_help()
        return

    print("\n💡 Подсказка: введите 'help' для справки\n")

    # Получаем список чатов
    while True:
        chat_input = input("📝 Введите ID чатов или @username (через запятую): ").strip()

        if chat_input.lower() == 'help':
            print_help()
            continue

        if not chat_input:
            print("❌ Введите хотя бы один чат!")
            continue

        break

    chat_ids = [c.strip() for c in chat_input.split(',')]

    # Лимит сообщений
    while True:
        limit_input = input("📊 Сколько сообщений импортировать? (Enter = все): ").strip()

        if not limit_input:
            limit = None
            break

        try:
            limit = int(limit_input)
            if limit <= 0:
                print("❌ Введите положительное число!")
                continue
            break
        except ValueError:
            print("❌ Введите корректное число!")
            continue

    # Подтверждение
    print(f"\n📋 Параметры импорта:")
    print(f"   Чатов: {len(chat_ids)}")
    for i, chat in enumerate(chat_ids, 1):
        print(f"      {i}. {chat}")
    print(f"   Лимит на чат: {limit if limit else 'Все сообщения'}")

    confirm = input("\n❓ Начать импорт? (y/n): ").strip().lower()
    if confirm != 'y':
        print("❌ Отменено")
        return

    # Запускаем импорт
    importer = ChatHistoryImporter()
    await importer.run(chat_ids, limit)


# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 Непредвиденная ошибка: {e}")
        sys.exit(1)