from __future__ import annotations

import aiohttp
import asyncio
import logging
import time
import random

logger = logging.getLogger(__name__)


class CaptchaSolver:
    def __init__(self, api_key: str, service: str = "rucaptcha"):
        self.api_key = api_key
        self.service = service
        self.create_task_url = "https://api.rucaptcha.com/createTask"
        self.get_result_url = "https://api.rucaptcha.com/getTaskResult"

        # ТВОЙ ПРОКСИ (вставлен)
        self.proxies = [
            {"type": "socks5", "host": "45.86.3.147", "port": 14893, "username": "user335792", "password": "9etya2"},
        ]

    async def solve_recaptcha_v2(
        self,
        sitekey: str,
        page_url: str = "https://web.telegram.org",
        timeout: int = 300,
    ) -> str:
        # Сначала пробуем с твоим прокси
        for proxy in self.proxies:
            try:
                logger.info(f"Пробую с прокси: {proxy['host']}:{proxy['port']}")
                return await self._solve_with_proxy(sitekey, page_url, timeout, proxy=proxy)
            except Exception as e:
                logger.warning(f"С прокси не сработало: {e}")
                await asyncio.sleep(2)

        # Если не сработало — пробуем без прокси
        try:
            logger.info("Пробую без прокси...")
            return await self._solve_with_proxy(sitekey, page_url, timeout, proxy=None)
        except Exception as e:
            logger.warning(f"Без прокси не сработало: {e}")

        raise Exception("Не удалось решить капчу")

    async def _solve_with_proxy(
        self,
        sitekey: str,
        page_url: str,
        timeout: int,
        proxy: dict | None,
    ) -> str:
        async with aiohttp.ClientSession() as session:
            user_agent = random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ])

            task_data = {
                "type": "RecaptchaV2Task" if proxy else "RecaptchaV2TaskProxyless",
                "websiteURL": page_url,
                "websiteKey": sitekey,
                "isInvisible": False,
                "userAgent": user_agent,
                "cookies": f"tg_web_session=; stel_web_auth=; _ga=GA1.2.{random.randint(100000, 999999)}.{int(time.time())}",
            }

            if proxy:
                task_data.update({
                    "proxyType": proxy["type"],
                    "proxyAddress": proxy["host"],
                    "proxyPort": int(proxy["port"]),
                })
                if proxy.get("username") and proxy.get("password"):
                    task_data["proxyLogin"] = proxy["username"]
                    task_data["proxyPassword"] = proxy["password"]

            task_payload = {
                "clientKey": self.api_key,
                "task": task_data,
                "softId": 3898,
                "languagePool": "en",
            }

            logger.info(f"Отправка капчи в RuCaptcha (с прокси: {proxy is not None})")

            async with session.post(self.create_task_url, json=task_payload) as resp:
                result = await resp.json()
                logger.info(f"Ответ createTask: {result}")

                if result.get("errorId", 0) != 0:
                    error_desc = result.get("errorDescription", "Unknown error")
                    raise Exception(f"Ошибка: {error_desc}")

                task_id = result.get("taskId")
                if not task_id:
                    raise Exception("Нет taskId")

                logger.info(f"Задача создана, ID: {task_id}")

            start_time = time.time()
            attempts = 0

            while time.time() - start_time < timeout:
                await asyncio.sleep(3)
                attempts += 1

                result_payload = {
                    "clientKey": self.api_key,
                    "taskId": task_id,
                }

                async with session.post(self.get_result_url, json=result_payload) as resp:
                    result = await resp.json()

                    if result.get("errorId", 0) != 0:
                        error_desc = result.get("errorDescription", "Unknown error")
                        raise Exception(f"Ошибка: {error_desc}")

                    status = result.get("status")
                    if status == "ready":
                        token = result.get("solution", {}).get("gRecaptchaResponse")
                        if token:
                            logger.info(f"✅ Капча решена!")
                            return token
                        raise Exception("Нет токена")

                    elif status == "processing":
                        if attempts % 5 == 0:
                            logger.info(f"Ожидаем... попытка {attempts}")
                        continue
                    else:
                        raise Exception(f"Неизвестный статус: {status}")

            raise TimeoutError(f"Таймаут {timeout}с")