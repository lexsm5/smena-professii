"""
Сервис «Смена профессии».
Запуск:  python main.py   →  http://127.0.0.1:8000

Необязательные переменные окружения (для блока «Вакансии на рынке»):
  HH_TOKEN  — токен приложения hh.ru (dev.hh.ru)
  SJ_KEY    — ключ приложения SuperJob (api.superjob.ru)
Без них подбор профессий и курсов работает полностью, не работает только блок с вакансиями.
"""
import os
import sqlite3
import statistics
import time
from urllib.parse import quote
from contextlib import closing

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Смена профессии")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "index.html")
DB_PATH = os.path.join(BASE_DIR, "database.db")

HH_TOKEN = os.getenv("HH_TOKEN", "")
SJ_KEY = os.getenv("SJ_KEY", "")

# ---------------------------------------------------------------------------
# БАЗА ЗНАНИЙ: навыки, профессии, курсы
# Чтобы добавить навык — добавь его в SKILL_GROUPS и (по желанию) в COURSES.
# Чтобы добавить профессию — добавь словарь в PROFESSIONS (веса навыков: 1–3).
# ---------------------------------------------------------------------------
SKILL_GROUPS = [
    ("data", "Данные и финансы", [
        ("excel", "Excel (продвинутый)"), ("sql", "SQL"), ("python", "Python"),
        ("statistics", "Статистика"), ("bi", "BI-системы (Power BI, Tableau)"),
        ("analytics", "Аналитическое мышление"), ("1c", "1С"),
        ("accounting", "Бухгалтерская отчётность"), ("finmodel", "Финансовое моделирование"),
    ]),
    ("dev", "Разработка и ИТ", [
        ("javascript", "JavaScript"), ("html_css", "HTML и CSS"), ("git", "Git"),
        ("api", "Работа с API"), ("algorithms", "Алгоритмы и структуры данных"),
        ("linux", "Linux и командная строка"), ("networks", "Сети и протоколы"),
        ("testing", "Тестирование ПО"),
    ]),
    ("creative", "Дизайн и контент", [
        ("design", "Визуальный дизайн"), ("figma", "Figma"), ("writing", "Копирайтинг"),
        ("smm", "SMM и соцсети"), ("seo", "SEO"), ("marketing", "Маркетинг"), ("photo", "Фотография"),
    ]),
    ("business", "Бизнес и управление", [
        ("projectmgmt", "Управление проектами"), ("product", "Продуктовое мышление"),
        ("sales", "Продажи"), ("crm", "Работа с CRM"), ("negotiation", "Переговоры"),
        ("timemgmt", "Тайм-менеджмент"), ("leadership", "Руководство командой"),
    ]),
    ("people", "Люди и коммуникации", [
        ("communication", "Общение с клиентами"), ("publicspeak", "Публичные выступления"),
        ("teamwork", "Работа в команде"), ("english", "Английский язык"),
        ("attentive", "Внимательность к деталям"), ("hr", "HR-процессы"),
        ("recruiting", "Подбор персонала"), ("teaching", "Преподавание и объяснение"),
    ]),
    ("care", "Уход и забота о людях и животных", [
        ("childcare", "Уход за детьми"), ("kids_activities", "Игры и занятия с детьми"),
        ("elder_care", "Уход за пожилыми и больными"), ("nursing", "Медицинский уход (давление, перевязки)"),
        ("first_aid", "Первая помощь"), ("pets", "Уход за животными"),
        ("grooming", "Груминг животных"), ("dog_training", "Дрессировка собак"),
        ("empathy", "Эмпатия и терпение"),
    ]),
    ("home", "Дом, быт и ремонт", [
        ("cooking", "Приготовление еды"), ("baking", "Выпечка и кондитерские изделия"),
        ("cleaning", "Уборка и поддержание порядка"), ("laundry", "Стирка и глажка"),
        ("sewing", "Шитьё и ремонт одежды"), ("gardening", "Садоводство и огород"),
        ("floristry", "Флористика, составление букетов"),
        ("home_repair", "Мелкий бытовой ремонт"), ("furniture_assembly", "Сборка мебели"),
        ("appliance_repair", "Ремонт бытовой техники"), ("carpentry", "Работа с деревом"),
        ("electrics", "Электромонтаж"), ("plumbing", "Сантехнические работы"),
        ("painting", "Малярные и отделочные работы"), ("tiling", "Укладка плитки"),
        ("masonry", "Кладка и бетонные работы"), ("welding", "Сварка"),
        ("auto_repair", "Ремонт и обслуживание автомобиля"),
    ]),
    ("transport", "Транспорт и склад", [
        ("driving", "Вождение (категория B)"), ("driving_c", "Вождение грузовика (категория C)"),
        ("forklift", "Управление погрузчиком"), ("navigation", "Знание города, ориентирование"),
        ("delivery", "Доставка заказов"), ("warehouse", "Складской учёт и комплектация"),
        ("physical", "Физическая выносливость"),
    ]),
    ("service", "Сфера услуг и торговля", [
        ("cashier", "Работа с кассой"), ("merch", "Выкладка товара, мерчандайзинг"),
        ("hospitality", "Обслуживание гостей и клиентов лично"), ("coffee", "Приготовление кофе"),
        ("bartending", "Приготовление коктейлей"), ("phone_calls", "Разговоры с клиентами по телефону"),
        ("security", "Охрана и наблюдение за порядком"), ("tour_guide", "Экскурсии и рассказ о местах"),
    ]),
    ("beauty", "Красота и здоровье", [
        ("hair", "Стрижки и укладки"), ("nails", "Маникюр и педикюр"),
        ("massage", "Массаж"), ("fitness", "Тренировки и фитнес"), ("makeup", "Макияж"),
    ]),
]

SKILL_NAMES = {sid: name for _, _, skills in SKILL_GROUPS for sid, name in skills}
SKILL_GROUP = {sid: gid for gid, _, skills in SKILL_GROUPS for sid, _ in skills}
# группы, где навыки в основном осваиваются офлайн (колледжи, учебные центры, практика)
OFFLINE_GROUPS = {"care", "home", "transport", "service", "beauty"}
# навыки, под которые нет курсов: развиваются практикой
NO_COURSE = {"attentive", "teamwork", "empathy", "physical", "navigation", "delivery", "cashier", "merch"}

# Как такому осваивают на практике (показывается под навыком у практических профессий).
# Формулировки общие: конкретные программы и условия зависят от города и учебного центра.
LEARN_HINT = {
    "childcare": "Курсы нянь, опыт с детьми в семье, рекомендации от родителей",
    "kids_activities": "Курсы раннего развития, практика с детьми",
    "elder_care": "Курсы сиделок и помощников по уходу, практика рядом с опытным специалистом",
    "nursing": "Медицинский колледж или курсы младшего медперсонала. Процедуры обычно можно делать только с профильным образованием",
    "first_aid": "Короткие курсы первой помощи в учебных центрах",
    "pets": "Опыт ухода за своими питомцами, курсы ассистентов ветеринара",
    "grooming": "Курсы груминга, практика на моделях",
    "dog_training": "Курсы кинологов, практика в клубе дрессировки",
    "cooking": "Практика и кулинарные курсы или колледж, начать можно помощником на кухне",
    "baking": "Курсы по выпечке и кондитерскому делу, стажировка в пекарне",
    "cleaning": "Быстро осваивается на стажировке у опытного напарника",
    "laundry": "Практика; нюансы ухода за тканями узнают у наставника или на курсах",
    "sewing": "Курсы кройки и шитья, практика в ателье",
    "gardening": "Практика на участке, помощником садовника, курсы садоводства и ландшафта",
    "floristry": "Курсы флористов, практика в цветочном салоне",
    "home_repair": "Практика, помощником мастера, видеоразборы",
    "furniture_assembly": "Практика помощником сборщика",
    "appliance_repair": "Курсы по ремонту техники, практика в сервисном центре",
    "carpentry": "Колледж или курсы столяров, практика в мастерской",
    "electrics": "Колледж или учебный центр, затем группа по электробезопасности",
    "plumbing": "Учебные центры и колледжи, практика в бригаде",
    "painting": "Практика в бригаде, курсы отделочников",
    "tiling": "Практика в бригаде, курсы плиточников",
    "masonry": "Учебные центры и колледжи, практика в бригаде",
    "welding": "Учебный центр с аттестацией, практика под руководством сварщика",
    "auto_repair": "Колледж или курсы автомехаников, практика в автосервисе",
    "driving": "Автошкола, категория B",
    "driving_c": "Автошкола, категория C",
    "forklift": "Учебный центр, удостоверение на управление погрузчиком",
    "warehouse": "Практика на складе, курсы по складской логистике и 1С",
    "cashier": "Обычно обучают на рабочем месте",
    "merch": "Обычно обучают на рабочем месте",
    "delivery": "Осваивается на старте работы, нужен транспорт или хорошая физическая форма",
    "navigation": "Приходит с практикой, помогают навигаторы и карты",
    "hospitality": "Практика в зале, стажировка",
    "coffee": "Курсы бариста, стажировка в кофейне",
    "bartending": "Курсы барменов, стажировка в баре",
    "phone_calls": "Скрипты и обучение у работодателя, практика",
    "security": "Обучение в лицензированной школе охраны, удостоверение частного охранника",
    "tour_guide": "Курсы экскурсоводов, подготовка своего маршрута",
    "hair": "Курсы парикмахеров или колледж, практика на моделях",
    "nails": "Курсы маникюра, практика на моделях",
    "massage": "Курсы массажа. Лечебный массаж обычно требует медицинского образования",
    "fitness": "Курсы фитнес-тренеров, сертификат",
    "makeup": "Курсы визажистов, практика на моделях",
}

# Прямые ссылки на курсы Нетологии (адреса взяты из каталога netology.ru): навык -> (название, адрес).
# Для остальных навыков сервис даёт ссылку на поиск (Skillbox и общий поиск).
NETOLOGY = "https://netology.ru/programs/"
COURSES = {
    "excel": ("Excel: от основ до анализа данных", "excel"),
    "sql": ("SQL с нуля", "sql-lessons"),
    "python": ("Python-разработчик для начинающих", "python-dev-basic"),
    "statistics": ("Математика для анализа данных", "mathematics-for-data-science"),
    "bi": ("Power BI", "power-bi"),
    "analytics": ("Введение в аналитику данных", "data-start"),
    "1c": ("1С-программист с нуля", "developer1c"),
    "accounting": ("Бухгалтерский учёт с нуля", "buhgalterskij-uchet-sz"),
    "finmodel": ("Профессия Финансовый аналитик", "financial_analyst"),
    "javascript": ("Frontend-разработчик (HTML, CSS, JavaScript)", "front-end"),
    "html_css": ("Курс по вёрстке сайтов", "htmlcssland"),
    "linux": ("Системный администратор (Windows и Linux)", "sysadmin"),
    "networks": ("Сетевой инженер", "network-engineer"),
    "testing": ("Инженер по тестированию", "qa"),
    "design": ("Основы графического дизайна", "mediadesign"),
    "figma": ("UX/UI-дизайнер", "ux-design"),
    "writing": ("Копирайтер", "editor-ed"),
    "smm": ("SMM-менеджер", "smm-specialist"),
    "seo": ("SEO-специалист", "seo-course"),
    "marketing": ("Интернет-маркетолог", "distance-course-internet-marketing"),
    "projectmgmt": ("Менеджер проектов", "project"),
    "product": ("Продакт-менеджер", "profession-product"),
    "sales": ("Курс по продажам", "sales_manager"),
    "negotiation": ("Деловые переговоры и коммуникации", "mba-negotiation"),
    "timemgmt": ("Тайм-менеджмент", "tajm-menedzhment-i-upravlenie-resursami"),
    "leadership": ("Лидерство в бизнесе", "mba-leadership"),
    "communication": ("Эффективные коммуникации", "effektivnye-kommunikacii"),
    "publicspeak": ("Публичные выступления", "publichnye-vystupleniya"),
    "hr": ("HR-менеджер", "hr-manager"),
    "recruiting": ("Подбор персонала (IT-рекрутинг)", "itrecruiter"),
    "teaching": ("Методист онлайн-курсов", "metodist-online-obucheniya"),
    "photo": ("Фотограф", "photographer"),
}

PROFESSIONS = [
    {"id": "data_analyst", "name": "Аналитик данных", "hh_query": "аналитик данных",
     "desc": "Достаёт выводы из данных: запросы, отчёты, дашборды.",
     "skills": {"sql": 3, "python": 3, "statistics": 2, "bi": 2, "analytics": 2, "excel": 1, "english": 1}},
    {"id": "fin_analyst", "name": "Финансовый аналитик", "hh_query": "финансовый аналитик",
     "desc": "Считает бюджеты, прогнозы и эффективность бизнеса.",
     "skills": {"excel": 3, "finmodel": 3, "accounting": 2, "analytics": 2, "bi": 1}},
    {"id": "report_auto", "name": "Специалист по автоматизации отчётности", "hh_query": "специалист по автоматизации отчётности",
     "desc": "Убирает ручной труд из отчётов: макросы, запросы, выгрузки.",
     "skills": {"excel": 3, "sql": 2, "1c": 2, "python": 1, "attentive": 1}},
    {"id": "business_analyst", "name": "Бизнес-аналитик", "hh_query": "бизнес-аналитик",
     "desc": "Превращает потребности бизнеса в требования к системе.",
     "skills": {"analytics": 3, "communication": 2, "sql": 2, "projectmgmt": 1, "excel": 1}},
    {"id": "product_manager", "name": "Продакт-менеджер", "hh_query": "продакт-менеджер",
     "desc": "Отвечает за продукт: что делать, зачем и в каком порядке.",
     "skills": {"product": 3, "projectmgmt": 2, "analytics": 2, "communication": 2, "teamwork": 1, "english": 1}},
    {"id": "project_manager", "name": "Менеджер проектов", "hh_query": "менеджер проектов",
     "desc": "Ведёт проект от задачи до сдачи: сроки, команда, бюджет.",
     "skills": {"projectmgmt": 3, "communication": 2, "timemgmt": 2, "leadership": 2, "teamwork": 1}},
    {"id": "ux_ui", "name": "UX/UI-дизайнер", "hh_query": "UX/UI дизайнер",
     "desc": "Проектирует удобные интерфейсы сайтов и приложений.",
     "skills": {"figma": 3, "design": 3, "analytics": 1, "communication": 1, "attentive": 1}},
    {"id": "graphic_designer", "name": "Графический дизайнер", "hh_query": "графический дизайнер",
     "desc": "Делает визуальную часть: баннеры, презентации, айдентику.",
     "skills": {"design": 3, "figma": 2, "communication": 1, "attentive": 1}},
    {"id": "frontend", "name": "Frontend-разработчик", "hh_query": "frontend разработчик",
     "desc": "Пишет то, что пользователь видит в браузере.",
     "skills": {"javascript": 3, "html_css": 3, "git": 2, "api": 1, "algorithms": 1, "english": 1}},
    {"id": "backend", "name": "Backend-разработчик (Python)", "hh_query": "python разработчик",
     "desc": "Строит серверную часть: логику, базы данных, API.",
     "skills": {"python": 3, "sql": 3, "api": 2, "git": 2, "linux": 1, "english": 1}},
    {"id": "qa", "name": "QA-инженер (тестировщик)", "hh_query": "тестировщик ПО",
     "desc": "Ищет ошибки до того, как их найдут пользователи.",
     "skills": {"testing": 3, "attentive": 2, "sql": 1, "api": 1, "analytics": 1, "git": 1}},
    {"id": "devops", "name": "DevOps-инженер", "hh_query": "devops инженер",
     "desc": "Настраивает серверы и автоматизирует выкладку кода.",
     "skills": {"linux": 3, "git": 2, "networks": 2, "python": 1}},
    {"id": "hr_manager", "name": "HR-менеджер", "hh_query": "HR менеджер",
     "desc": "Работает с командой: адаптация, обучение, кадровые процессы.",
     "skills": {"hr": 3, "recruiting": 2, "communication": 2, "publicspeak": 1}},
    {"id": "recruiter", "name": "Рекрутёр", "hh_query": "рекрутер",
     "desc": "Ищет и подбирает людей на вакансии.",
     "skills": {"recruiting": 3, "communication": 3, "hr": 1, "crm": 1}},
    {"id": "content_marketer", "name": "Контент-маркетолог", "hh_query": "контент-маркетолог",
     "desc": "Привлекает аудиторию полезными текстами и материалами.",
     "skills": {"writing": 3, "smm": 2, "marketing": 2, "seo": 1, "analytics": 1}},
    {"id": "smm", "name": "SMM-менеджер", "hh_query": "SMM менеджер",
     "desc": "Ведёт соцсети бренда и растит аудиторию.",
     "skills": {"smm": 3, "writing": 2, "marketing": 2, "design": 1, "analytics": 1}},
    {"id": "seo", "name": "SEO-специалист", "hh_query": "SEO специалист",
     "desc": "Выводит сайты в топ поисковой выдачи.",
     "skills": {"seo": 3, "analytics": 2, "writing": 1, "html_css": 1}},
    {"id": "sales_manager", "name": "Менеджер по продажам", "hh_query": "менеджер по продажам",
     "desc": "Находит клиентов и доводит сделки до оплаты.",
     "skills": {"sales": 3, "communication": 3, "crm": 2, "negotiation": 2, "timemgmt": 1}},
    {"id": "customer_success", "name": "Менеджер по работе с клиентами", "hh_query": "менеджер по работе с клиентами",
     "desc": "Сопровождает клиентов и удерживает их после покупки.",
     "skills": {"communication": 3, "crm": 2, "negotiation": 1, "attentive": 1, "teamwork": 1}},
    {"id": "online_teacher", "name": "Онлайн-преподаватель / методист", "hh_query": "методист онлайн курсов",
     "desc": "Объясняет и строит программы обучения.",
     "skills": {"teaching": 3, "communication": 2, "publicspeak": 2, "writing": 1}},
    {"id": "nanny", "name": "Няня", "hh_query": "няня",
     "desc": "Присматривает за детьми, кормит, развивает, следит за безопасностью.",
     "note": "Родители обычно просят опыт, рекомендации и медицинскую книжку.",
     "skills": {"childcare": 3, "kids_activities": 2, "empathy": 2, "first_aid": 2, "cooking": 1, "cleaning": 1, "communication": 1, "attentive": 1}},
    {"id": "caregiver", "name": "Сиделка / помощник по уходу", "hh_query": "сиделка",
     "desc": "Помогает пожилым и больным людям в быту и самочувствии.",
     "note": "Опыт и рекомендации ценятся больше всего; медицинские процедуры обычно требуют профильного образования.",
     "skills": {"elder_care": 3, "empathy": 3, "first_aid": 2, "nursing": 1, "cooking": 1, "cleaning": 1, "physical": 1}},
    {"id": "gardener", "name": "Садовник", "hh_query": "садовник",
     "desc": "Ухаживает за садом, газонами, клумбами и деревьями.",
     "skills": {"gardening": 3, "physical": 2, "home_repair": 1, "attentive": 1}},
    {"id": "landscape", "name": "Ландшафтный дизайнер", "hh_query": "ландшафтный дизайнер",
     "desc": "Проектирует сады и участки, подбирает растения и планировку.",
     "skills": {"gardening": 3, "design": 2, "communication": 1, "attentive": 1}},
    {"id": "cook", "name": "Повар", "hh_query": "повар",
     "desc": "Готовит блюда по рецептам, следит за качеством и чистотой.",
     "note": "Для работы с едой обычно нужна санитарная книжка.",
     "skills": {"cooking": 3, "cleaning": 1, "timemgmt": 1, "teamwork": 1, "physical": 1, "attentive": 1}},
    {"id": "barista", "name": "Бариста", "hh_query": "бариста",
     "desc": "Готовит кофе и напитки, общается с гостями.",
     "skills": {"coffee": 3, "hospitality": 2, "communication": 2, "cashier": 1, "teamwork": 1}},
    {"id": "waiter", "name": "Официант / администратор зала", "hh_query": "официант",
     "desc": "Встречает гостей, принимает заказы, обслуживает столы.",
     "skills": {"hospitality": 3, "communication": 2, "cashier": 1, "teamwork": 1, "timemgmt": 1}},
    {"id": "hotel_admin", "name": "Администратор гостиницы", "hh_query": "администратор гостиницы",
     "desc": "Встречает и заселяет гостей, решает вопросы проживания.",
     "skills": {"hospitality": 3, "communication": 3, "english": 1, "crm": 1, "attentive": 1}},
    {"id": "cleaner", "name": "Клинер / горничная", "hh_query": "клинер",
     "desc": "Поддерживает чистоту в домах, офисах и отелях.",
     "skills": {"cleaning": 3, "physical": 2, "attentive": 2, "timemgmt": 1}},
    {"id": "seamstress", "name": "Швея / портной", "hh_query": "швея",
     "desc": "Шьёт и ремонтирует одежду и текстиль.",
     "skills": {"sewing": 3, "attentive": 2, "design": 1, "timemgmt": 1}},
    {"id": "hairdresser", "name": "Парикмахер", "hh_query": "парикмахер",
     "desc": "Стрижёт, красит, делает укладки.",
     "skills": {"hair": 3, "communication": 2, "makeup": 1, "attentive": 1}},
    {"id": "nail_master", "name": "Мастер маникюра", "hh_query": "мастер маникюра",
     "desc": "Делает маникюр и педикюр, ведёт своих клиентов.",
     "skills": {"nails": 3, "attentive": 2, "communication": 1, "smm": 1}},
    {"id": "massage", "name": "Массажист", "hh_query": "массажист",
     "desc": "Проводит массаж и помогает клиентам расслабиться и восстановиться.",
     "note": "Лечебный массаж обычно требует медицинского образования; для расслабляющего хватает курсов и практики.",
     "skills": {"massage": 3, "first_aid": 1, "empathy": 1, "physical": 1, "communication": 1}},
    {"id": "fitness", "name": "Фитнес-тренер", "hh_query": "фитнес тренер",
     "desc": "Проводит тренировки и подбирает нагрузку клиентам.",
     "skills": {"fitness": 3, "communication": 2, "first_aid": 1, "teaching": 1, "empathy": 1}},
    {"id": "makeup_artist", "name": "Визажист", "hh_query": "визажист",
     "desc": "Делает макияж для съёмок, мероприятий и повседневной жизни.",
     "skills": {"makeup": 3, "design": 1, "communication": 1, "attentive": 1}},
    {"id": "driver", "name": "Водитель", "hh_query": "водитель",
     "desc": "Возит людей и грузы, укладывается в сроки.",
     "note": "Нужны права нужной категории и стаж.",
     "skills": {"driving": 3, "timemgmt": 2, "attentive": 1, "communication": 1}},
    {"id": "warehouse", "name": "Кладовщик / комплектовщик", "hh_query": "кладовщик",
     "desc": "Принимает, хранит и собирает заказы на складе.",
     "skills": {"warehouse": 3, "attentive": 2, "physical": 2, "1c": 1}},
    {"id": "handyman", "name": "Мастер на все руки", "hh_query": "мастер по ремонту",
     "desc": "Решает бытовые поломки и мелкий ремонт в квартирах и домах.",
     "skills": {"home_repair": 3, "electrics": 1, "plumbing": 1, "carpentry": 1, "painting": 1}},
    {"id": "electrician", "name": "Электрик", "hh_query": "электрик",
     "desc": "Монтирует и обслуживает электропроводку и оборудование.",
     "note": "Для работы с электроустановками требуется группа по электробезопасности.",
     "skills": {"electrics": 3, "attentive": 2, "home_repair": 1, "physical": 1}},
    {"id": "plumber", "name": "Сантехник", "hh_query": "сантехник",
     "desc": "Устанавливает и ремонтирует трубы, смесители, сантехнику.",
     "skills": {"plumbing": 3, "home_repair": 1, "physical": 1, "attentive": 1}},
    {"id": "carpenter", "name": "Плотник / столяр", "hh_query": "плотник",
     "desc": "Работает с деревом: мебель, двери, конструкции.",
     "skills": {"carpentry": 3, "attentive": 2, "physical": 1, "home_repair": 1}},
    {"id": "finisher", "name": "Маляр-отделочник", "hh_query": "маляр отделочник",
     "desc": "Красит, штукатурит, клеит обои, готовит помещения к жизни.",
     "skills": {"painting": 3, "attentive": 2, "physical": 1, "home_repair": 1}},
    {"id": "welder", "name": "Сварщик", "hh_query": "сварщик",
     "desc": "Соединяет металлические детали сваркой.",
     "note": "Работодатели обычно требуют удостоверение сварщика (аттестацию).",
     "skills": {"welding": 3, "attentive": 2, "physical": 1}},
    {"id": "seller", "name": "Продавец-консультант / кассир", "hh_query": "продавец консультант",
     "desc": "Консультирует покупателей, выкладывает товар, работает с кассой.",
     "skills": {"communication": 3, "cashier": 2, "merch": 2, "sales": 1, "attentive": 1}},
    {"id": "pet_sitter", "name": "Зооняня / помощник по уходу за животными", "hh_query": "зооняня",
     "desc": "Выгуливает, кормит и присматривает за питомцами.",
     "skills": {"pets": 3, "empathy": 1, "attentive": 1, "cleaning": 1}},
    {"id": "photographer", "name": "Фотограф", "hh_query": "фотограф",
     "desc": "Снимает людей, события и продукты, обрабатывает кадры.",
     "skills": {"photo": 3, "communication": 2, "design": 1, "attentive": 1}},

    # ---- уход и работа с детьми, животными ----
    {"id": "kindergarten_helper", "name": "Помощник воспитателя", "hh_query": "помощник воспитателя",
     "desc": "Помогает воспитателю в детском саду: кормление, прогулки, игры, порядок в группе.",
     "note": "В детских учреждениях обычно требуется медицинская книжка.",
     "skills": {"childcare": 3, "kids_activities": 3, "empathy": 2, "cleaning": 1, "first_aid": 1}},
    {"id": "tutor", "name": "Репетитор", "hh_query": "репетитор",
     "desc": "Занимается с учениками по предмету и помогает подтянуть оценки.",
     "skills": {"teaching": 3, "communication": 2, "empathy": 1, "publicspeak": 1}},
    {"id": "orderly", "name": "Санитар / младший медперсонал", "hh_query": "санитар",
     "desc": "Помогает пациентам и поддерживает порядок в больнице или пансионате.",
     "note": "Обычно нужна медицинская книжка; врачебные процедуры выполняет только медицинский персонал.",
     "skills": {"elder_care": 2, "nursing": 2, "cleaning": 1, "empathy": 2, "physical": 1, "first_aid": 1}},
    {"id": "groomer", "name": "Грумер", "hh_query": "грумер",
     "desc": "Стрижёт, купает и ухаживает за шерстью кошек и собак.",
     "skills": {"grooming": 3, "pets": 2, "attentive": 1, "physical": 1}},
    {"id": "cynologist", "name": "Кинолог / дрессировщик", "hh_query": "кинолог",
     "desc": "Обучает собак командам и помогает хозяевам справляться с поведением питомцев.",
     "skills": {"dog_training": 3, "pets": 2, "empathy": 1, "teaching": 1, "communication": 1}},
    {"id": "housekeeper", "name": "Домработница / помощница по хозяйству", "hh_query": "домработница",
     "desc": "Убирает, стирает, гладит и поддерживает порядок в доме.",
     "skills": {"cleaning": 3, "laundry": 2, "cooking": 1, "attentive": 1, "timemgmt": 1}},

    # ---- еда и сервис ----
    {"id": "baker", "name": "Пекарь / кондитер", "hh_query": "пекарь",
     "desc": "Печёт хлеб, выпечку и десерты по рецептам.",
     "note": "Для работы с едой обычно нужна санитарная книжка.",
     "skills": {"baking": 3, "cooking": 2, "attentive": 1, "physical": 1, "timemgmt": 1}},
    {"id": "bartender", "name": "Бармен", "hh_query": "бармен",
     "desc": "Готовит напитки и коктейли, общается с гостями за стойкой.",
     "skills": {"bartending": 3, "hospitality": 2, "communication": 1, "cashier": 1, "coffee": 1}},
    {"id": "call_operator", "name": "Оператор контакт-центра", "hh_query": "оператор колл-центра",
     "desc": "Принимает звонки и отвечает на вопросы клиентов по скрипту.",
     "skills": {"phone_calls": 3, "communication": 2, "crm": 1, "empathy": 1, "attentive": 1}},
    {"id": "tour_guide", "name": "Экскурсовод", "hh_query": "экскурсовод",
     "desc": "Проводит экскурсии и рассказывает гостям об истории и достопримечательностях.",
     "skills": {"tour_guide": 3, "publicspeak": 2, "communication": 1, "english": 1}},
    {"id": "security_guard", "name": "Охранник", "hh_query": "охранник",
     "desc": "Следит за порядком и безопасностью на объекте.",
     "note": "Для работы в охранной организации обычно нужно удостоверение частного охранника.",
     "skills": {"security": 3, "attentive": 2, "physical": 1, "communication": 1}},

    # ---- ремонт и стройка ----
    {"id": "car_mechanic", "name": "Автомеханик", "hh_query": "автомеханик",
     "desc": "Диагностирует и ремонтирует автомобили.",
     "skills": {"auto_repair": 3, "attentive": 2, "electrics": 1, "physical": 1, "driving": 1}},
    {"id": "appliance_master", "name": "Мастер по ремонту бытовой техники", "hh_query": "мастер по ремонту бытовой техники",
     "desc": "Чинит стиральные машины, холодильники и другую технику.",
     "skills": {"appliance_repair": 3, "electrics": 2, "attentive": 1, "communication": 1}},
    {"id": "bricklayer", "name": "Каменщик / бетонщик", "hh_query": "каменщик",
     "desc": "Кладёт кирпич и блоки, заливает бетонные основания.",
     "skills": {"masonry": 3, "physical": 2, "attentive": 1, "teamwork": 1}},
    {"id": "tiler", "name": "Плиточник", "hh_query": "плиточник",
     "desc": "Облицовывает стены и полы плиткой.",
     "skills": {"tiling": 3, "attentive": 2, "painting": 1, "physical": 1}},
    {"id": "furniture_assembler", "name": "Сборщик мебели", "hh_query": "сборщик мебели",
     "desc": "Собирает и устанавливает мебель у клиентов.",
     "skills": {"furniture_assembly": 3, "home_repair": 1, "carpentry": 1, "attentive": 1}},
    {"id": "florist", "name": "Флорист", "hh_query": "флорист",
     "desc": "Составляет букеты и композиции, оформляет мероприятия цветами.",
     "skills": {"floristry": 3, "design": 1, "gardening": 1, "communication": 1, "attentive": 1}},
    {"id": "greenhouse_worker", "name": "Работник теплицы / фермы", "hh_query": "работник теплицы",
     "desc": "Выращивает и собирает овощи, цветы и другие культуры.",
     "skills": {"gardening": 3, "physical": 2, "attentive": 1, "pets": 1}},

    # ---- транспорт и склад ----
    {"id": "courier", "name": "Курьер", "hh_query": "курьер",
     "desc": "Доставляет заказы и документы клиентам по городу.",
     "skills": {"delivery": 3, "navigation": 2, "timemgmt": 1, "physical": 1, "communication": 1}},
    {"id": "taxi_driver", "name": "Водитель такси", "hh_query": "водитель такси",
     "desc": "Возит пассажиров по заказам.",
     "skills": {"driving": 3, "navigation": 3, "communication": 1, "hospitality": 1}},
    {"id": "truck_driver", "name": "Водитель-дальнобойщик", "hh_query": "водитель категории C",
     "desc": "Перевозит грузы на грузовике на дальние расстояния.",
     "note": "Нужны права категории C и стаж; рейсы часто длительные.",
     "skills": {"driving_c": 3, "driving": 2, "attentive": 1, "timemgmt": 1, "physical": 1}},
    {"id": "forklift_driver", "name": "Водитель погрузчика", "hh_query": "водитель погрузчика",
     "desc": "Перемещает грузы на складе и в цеху на погрузчике.",
     "skills": {"forklift": 3, "warehouse": 2, "attentive": 1}},
    {"id": "loader", "name": "Грузчик", "hh_query": "грузчик",
     "desc": "Грузит, разгружает и перемещает товары и мебель.",
     "skills": {"physical": 3, "teamwork": 1, "warehouse": 1, "attentive": 1}},
]
PROF_BY_ID = {p["id"]: p for p in PROFESSIONS}


# ---------------------------------------------------------------------------
# БАЗА ДАННЫХ (SQLite): история подборов
# ---------------------------------------------------------------------------
def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS match_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skills TEXT,
                top_profession TEXT,
                top_pct INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(match_history)")]
        if "client_id" not in cols:
            conn.execute("ALTER TABLE match_history ADD COLUMN client_id TEXT")
        conn.commit()


init_db()


# ---------------------------------------------------------------------------
# МОДЕЛИ ЗАПРОСОВ
# ---------------------------------------------------------------------------
class MatchRequest(BaseModel):
    skills: list[str]
    client_id: str = ""


class VacancyRequest(BaseModel):
    profession_id: str


# ---------------------------------------------------------------------------
# АЛГОРИТМ ПОДБОРА
# Совпадение (%) = (сумма весов навыков, которые есть у пользователя)
#                  / (сумма весов всех навыков профессии) × 100
# ---------------------------------------------------------------------------
def _search(query):
    return "https://yandex.ru/search/?text=" + quote(query)


def course_info(skill, weight):
    """Куда идти учиться навыку: Нетология (прямая ссылка), Skillbox (поиск), общий поиск."""
    name = SKILL_NAMES[skill]
    courses = []
    if skill not in NO_COURSE:
        direct = COURSES.get(skill)
        if direct:
            courses.append({"platform": "Нетология", "title": direct[0],
                            "url": NETOLOGY + direct[1], "direct": True})
        if SKILL_GROUP[skill] not in OFFLINE_GROUPS:
            courses.append({"platform": "Skillbox", "title": f"Курсы Skillbox по теме «{name}»",
                            "url": _search(f"site:skillbox.ru {name} курс"), "direct": False})
        if not direct:
            courses.append({"platform": "Поиск", "title": "Найти курсы и учебные центры",
                            "url": _search(f"{name} курсы обучение с нуля"), "direct": False})
    return {"skill": name, "weight": weight, "courses": courses, "hint": LEARN_HINT.get(skill)}


MIN_PCT = 20  # совпадения слабее этого порога считаем шумом (кроме случая, когда подходящего почти нет)


def compute_matches(user_skills: set):
    results = []
    for prof in PROFESSIONS:
        total = sum(prof["skills"].values())
        have, missing, have_weight = [], [], 0
        for skill, weight in sorted(prof["skills"].items(), key=lambda x: -x[1]):
            if skill in user_skills:
                have_weight += weight
                have.append(SKILL_NAMES[skill])
            else:
                missing.append(course_info(skill, weight))
        pct = round(have_weight / total * 100)
        if pct > 0:
            results.append({
                "id": prof["id"], "name": prof["name"], "desc": prof["desc"],
                "note": prof.get("note"),
                "pct": pct, "have": have, "missing": missing,
            })
    results.sort(key=lambda r: -r["pct"])
    strong = [r for r in results if r["pct"] >= MIN_PCT]
    return strong if len(strong) >= 3 else results[:5]


# ---------------------------------------------------------------------------
# ВАКАНСИИ ЧЕРЕЗ ОФИЦИАЛЬНЫЕ API (hh.ru, SuperJob)
# ---------------------------------------------------------------------------
_vac_cache = {}
CACHE_TTL = 600  # секунд


async def fetch_hh(query: str):
    headers = {"User-Agent": "SmenaProfessii/1.0 (student project)"}
    if HH_TOKEN:
        headers["Authorization"] = f"Bearer {HH_TOKEN}"
    params = {"text": query, "area": 113, "per_page": 20, "order_by": "publication_time"}
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get("https://api.hh.ru/vacancies", params=params, headers=headers)
    if r.status_code in (401, 403):
        raise RuntimeError("hh.ru требует токен приложения (переменная HH_TOKEN)")
    r.raise_for_status()
    data = r.json()
    items, salaries = [], []
    for it in data.get("items", []):
        s = it.get("salary") or {}
        vals = [v for v in (s.get("from"), s.get("to")) if v]
        if vals and s.get("currency") in ("RUR", "RUB"):
            salaries.append(sum(vals) / len(vals))
        items.append({
            "title": it.get("name"),
            "company": (it.get("employer") or {}).get("name", "Не указана"),
            "url": it.get("alternate_url"),
        })
    return {"source": "hh.ru", "total": data.get("found", len(items)), "items": items[:5], "salaries": salaries}


async def fetch_superjob(query: str):
    headers = {"X-Api-App-Id": SJ_KEY}
    params = {"keyword": query, "count": 20}
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get("https://api.superjob.ru/2.0/vacancies/", params=params, headers=headers)
    r.raise_for_status()
    data = r.json()
    items, salaries = [], []
    for it in data.get("objects", []):
        vals = [v for v in (it.get("payment_from"), it.get("payment_to")) if v]
        if vals and it.get("currency") == "rub":
            salaries.append(sum(vals) / len(vals))
        items.append({
            "title": it.get("profession"),
            "company": it.get("firm_name") or "Не указана",
            "url": it.get("link"),
        })
    return {"source": "SuperJob", "total": data.get("total", len(items)), "items": items[:5], "salaries": salaries}


async def get_vacancies(prof):
    cached = _vac_cache.get(prof["id"])
    if cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]

    errors, sources = [], [fetch_hh]
    if SJ_KEY:
        sources.append(fetch_superjob)

    for fetcher in sources:
        try:
            res = await fetcher(prof["hh_query"])
            salaries = res.pop("salaries")
            res["median_salary"] = round(statistics.median(salaries), -3) if salaries else None
            res["available"] = True
            _vac_cache[prof["id"]] = (time.time(), res)
            return res
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))

    return {"available": False, "reason": "; ".join(errors) or "источник недоступен"}


# ---------------------------------------------------------------------------
# МАРШРУТЫ
# ---------------------------------------------------------------------------
@app.get("/")
async def read_index():
    return FileResponse(INDEX_PATH)


@app.get("/api/catalog")
async def catalog():
    return {
        "groups": [
            {"id": gid, "title": title, "skills": [{"id": s, "name": n} for s, n in skills]}
            for gid, title, skills in SKILL_GROUPS
        ],
        "professions_total": len(PROFESSIONS),
    }


@app.post("/api/match")
async def match(req: MatchRequest):
    user_skills = {s for s in req.skills if s in SKILL_NAMES}
    results = compute_matches(user_skills)
    if results:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.execute(
                "INSERT INTO match_history (skills, top_profession, top_pct, client_id) VALUES (?, ?, ?, ?)",
                (",".join(sorted(user_skills)), results[0]["name"], results[0]["pct"], req.client_id[:64]),
            )
            conn.commit()
    return {"results": results}


@app.post("/api/vacancies")
async def vacancies(req: VacancyRequest):
    prof = PROF_BY_ID.get(req.profession_id)
    if not prof:
        return {"available": False, "reason": "неизвестная профессия"}
    return await get_vacancies(prof)


@app.get("/api/history")
async def history(client_id: str = ""):
    if not client_id:
        return {"items": []}
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT top_profession, top_pct, skills, timestamp FROM match_history "
            "WHERE client_id = ? ORDER BY id DESC LIMIT 6",
            (client_id[:64],),
        ).fetchall()
    return {"items": [
        {"profession": r[0], "pct": r[1], "skills_count": len([s for s in (r[2] or "").split(",") if s]), "time": r[3]}
        for r in rows
    ]}


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print(f"Сервер запущен: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
