from __future__ import annotations

import aiohttp
import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class CaptchaSolver:
    def __init__(self, api_key: str, service: str = "rucaptcha"):
        self.api_key = api_key
        self.service = service
        self.create_task_url = "https://api.rucaptcha.com/createTask"
        self.get_result_url = "https://api.rucaptcha.com/getTaskResult"

        # ===== ТВОЙ ПРОКСИ =====
        self.proxy = {
            "type": "socks5",
            "host": "45.86.3.147",
            "port": 14893,
            "username": "user335792",
            "password": "9etya2",
        }

    async def solve_recaptcha_v2(
        self,
        sitekey: str,
        page_url: str = "https://web.telegram.org",
        timeout: int = 300,
    ) -> str:
        async with aiohttp.ClientSession() as session:
            # Используем метод RecaptchaV2Task (с прокси)
            task_data = {
                "type": "RecaptchaV2Task",
                "websiteURL": page_url,
                "websiteKey": sitekey,
                "isInvisible": False,
                "proxyType": self.proxy["type"],
                "proxyAddress": self.proxy["host"],
                "proxyPort": self.proxy["port"],
                "proxyLogin": self.proxy["username"],
                "proxyPassword": self.proxy["password"],
                "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }

            task_payload = {
                "clientKey": self.api_key,
                "task": task_data,
                "softId": 3898,
            }

            logger.info(f"Отправка капчи через прокси: {self.proxy['host']}:{self.proxy['port']}")

            async with session.post(self.create_task_url, json=task_payload) as resp:
                result = await resp.json()
                logger.info(f"Ответ createTask: {result}")

                if result.get("errorId", 0) != 0:
                    error_desc = result.get("errorDescription", "Unknown error")
                    raise Exception(f"Ошибка RuCaptcha: {error_desc}")

                task_id = result.get("taskId")
                if not task_id:
                    raise Exception("RuCaptcha не вернул taskId")

                logger.info(f"Задача создана, taskId: {task_id}")

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
                    logger.debug(f"Попытка {attempts}: {result}")

                    if result.get("errorId", 0) != 0:
                        error_desc = result.get("errorDescription", "Unknown error")
                        raise Exception(f"Ошибка RuCaptcha: {error_desc}")

                    status = result.get("status")
                    if status == "ready":
                        token = result.get("solution", {}).get("gRecaptchaResponse")
                        if token:
                            logger.info(f"✅ Капча решена через твой прокси!")
                            return token
                        raise Exception("Нет токена")

                    elif status == "processing":
                        if attempts % 5 == 0:
                            logger.info(f"Ожидаем... попытка {attempts}")
                        continue
                    else:
                        raise Exception(f"Неизвестный статус: {status}")