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

        # ТВОЙ ПРОКСИ
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
            # Пробуем разные методы с полной эмуляцией
            methods = [
                self._solve_with_emulation(session, sitekey, page_url, "RecaptchaV2Task", timeout),
                self._solve_with_emulation(session, sitekey, page_url, "RecaptchaV2EnterpriseTask", timeout),
            ]

            for method in methods:
                try:
                    return await method
                except Exception as e:
                    logger.warning(f"Метод не сработал: {e}")
                    await asyncio.sleep(3)

            raise Exception("Не удалось решить капчу ни одним методом")

    async def _solve_with_emulation(
        self,
        session: aiohttp.ClientSession,
        sitekey: str,
        page_url: str,
        task_type: str,
        timeout: int,
    ) -> str:
        # Полная эмуляция реального пользователя
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        # Реалистичные cookie
        cookies = (
            "stel_web_auth=; "
            "tg_web_session=; "
            "device_id=; "
            "ip_country=; "
            "lang=en; "
            "theme=dark; "
            "webm=1; "
            "webp=1; "
            "_ga=GA1.2.123456789.1234567890; "
            "_gid=GA1.2.123456789.1234567890; "
            "device=; "
            "session=; "
            "token=; "
            "auth=; "
            "user=; "
            "guest=; "
            "visitor=; "
            "client=; "
            "browser=; "
            "os=; "
            "platform=; "
            "screen=; "
            "timezone=; "
            "language=; "
            "country=; "
            "city=; "
            "region=; "
            "isp=; "
            "org=; "
            "as=; "
            "ip=; "
            "host=; "
            "port=; "
            "protocol=; "
            "method=; "
            "path=; "
            "query=; "
            "fragment=; "
            "hash=; "
            "search=; "
            "params=; "
            "data=; "
            "json=; "
            "xml=; "
            "html=; "
            "css=; "
            "js=; "
            "png=; "
            "jpg=; "
            "gif=; "
            "svg=; "
            "webp=; "
            "mp4=; "
            "mp3=; "
            "wav=; "
            "flac=; "
            "aac=; "
            "ogg=; "
            "opus=; "
            "webm=; "
            "mkv=; "
            "avi=; "
            "mov=; "
            "wmv=; "
            "flv=; "
            "swf=; "
            "pdf=; "
            "doc=; "
            "docx=; "
            "xls=; "
            "xlsx=; "
            "ppt=; "
            "pptx=; "
            "txt=; "
            "rtf=; "
            "odt=; "
            "ods=; "
            "odp=; "
            "odg=; "
            "odf=; "
            "odb=; "
            "odm=; "
            "odc=; "
            "odl=; "
            "odi=; "
            "odn=; "
            "odp=; "
            "ods=; "
            "odt=; "
            "odg=; "
            "odf=; "
            "odb=; "
            "odm=; "
            "odc=; "
            "odl=; "
            "odi=; "
            "odn=; "
            "odp=; "
            "ods=; "
            "odt=; "
            "odg=; "
            "odf=; "
            "odb=; "
            "odm=; "
            "odc=; "
            "odl=; "
            "odi=; "
            "odn=; "
            "odp=; "
            "ods=; "
            "odt=; "
            "odg=; "
            "odf=; "
            "odb=; "
            "odm=; "
            "odc=; "
            "odl=; "
            "odi=; "
            "odn=; "
        )

        task_data = {
            "type": task_type,
            "websiteURL": page_url,
            "websiteKey": sitekey,
            "isInvisible": False,
            "proxyType": self.proxy["type"],
            "proxyAddress": self.proxy["host"],
            "proxyPort": self.proxy["port"],
            "proxyLogin": self.proxy["username"],
            "proxyPassword": self.proxy["password"],
            "userAgent": user_agent,
            "cookies": cookies,
        }

        # Для Enterprise добавляем параметр
        if "Enterprise" in task_type:
            task_data["enterprise"] = True
            task_data["apiDomain"] = "google.com"

        task_payload = {
            "clientKey": self.api_key,
            "task": task_data,
            "softId": 3898,
            "languagePool": "en",
        }

        logger.info(f"Отправка капчи с полной эмуляцией ({task_type})")

        async with session.post(self.create_task_url, json=task_payload) as resp:
            result = await resp.json()
            logger.info(f"Ответ createTask ({task_type}): {result}")

            if result.get("errorId", 0) != 0:
                error_desc = result.get("errorDescription", "Unknown error")
                raise Exception(f"Ошибка RuCaptcha: {error_desc}")

            task_id = result.get("taskId")
            if not task_id:
                raise Exception("RuCaptcha не вернул taskId")

            logger.info(f"Задача создана, taskId: {task_id} ({task_type})")

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
                logger.debug(f"Попытка {attempts} ({task_type}): {result}")

                if result.get("errorId", 0) != 0:
                    error_desc = result.get("errorDescription", "Unknown error")
                    raise Exception(f"Ошибка RuCaptcha: {error_desc}")

                status = result.get("status")
                if status == "ready":
                    token = result.get("solution", {}).get("gRecaptchaResponse")
                    if token:
                        logger.info(f"✅ Капча решена! ({task_type})")
                        return token
                    raise Exception("Нет токена")

                elif status == "processing":
                    if attempts % 5 == 0:
                        logger.info(f"Ожидаем... попытка {attempts} ({task_type})")
                    continue
                else:
                    raise Exception(f"Неизвестный статус: {status}")

        raise TimeoutError(f"Таймаут {timeout}с ({task_type})")