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

    async def solve_recaptcha_v2(
        self,
        sitekey: str,
        page_url: str = "https://web.telegram.org",
        timeout: int = 240,
    ) -> str:
        async with aiohttp.ClientSession() as session:
            # Используем параметры, максимально похожие на реального пользователя
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
            # Генерируем реалистичные cookie
            cookies = (
                "tg_web_session=; "
                "stel_web_auth=; "
                f"_ga=GA1.2.{random.randint(100000, 999999)}.{int(time.time())}; "
                f"_gid=GA1.2.{random.randint(100000, 999999)}.{int(time.time())}; "
                "device_id=; "
                "ip_country=; "
                "lang=en; "
                "theme=dark; "
                "webm=1; "
                "webp=1"
            )

            task_payload = {
                "clientKey": self.api_key,
                "task": {
                    "type": "RecaptchaV2TaskProxyless",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                    "isInvisible": False,
                    "userAgent": user_agent,
                    "cookies": cookies,
                    # Добавляем дополнительные параметры
                    "recaptchaDataSValue": "some_value",  # для некоторых версий
                },
                "softId": 3898,
                "languagePool": "en",  # английский язык
            }

            logger.info(f"Отправка капчи с полной эмуляцией браузера...")

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
                        continue
                    else:
                        raise Exception(f"Неизвестный статус: {status}")

            raise TimeoutError(f"Таймаут {timeout}с")