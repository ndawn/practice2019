#! /usr/bin/python3

import sys
import re
import os.path
import atexit
import json
import random
from getpass import getpass
from typing import Union, Dict

import requests
from bs4 import BeautifulSoup


PROXY_LIST_URL = 'https://premproxy.com/ru/proxy-by-country/list-ip-port/%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D1%8F-01.htm'
AUTH_URL = 'https://elibrary.ru/start_session.asp'
AUTHOR_LIST_URL = 'https://elibrary.ru/authors.asp'
AUTHOR_ITEMS_URL = 'https://elibrary.ru/author_items.asp'
AUTHOR_REFS_URL = 'https://elibrary.ru/author_refs.asp'


class Config:
    def __init__(self):
        self._cookies = None
        self.proxies = None
        self._session = requests.Session()

    @property
    def cookies(self):
        if self._cookies is None:
            self.load_cookies()

        return self._cookies

    @cookies.setter
    def cookies(self, value: dict):
        self._cookies = value

    @property
    def session(self):
        return self._session

    def save_cookies(self):
        with open('cookies.json', 'w') as file:
            json.dump(self._cookies, file)

    def load_cookies(self):
        if os.path.exists('cookies.json'):
            with open('cookies.json', 'r') as file:
                self._cookies = json.load(file)
        else:
            self._cookies = {}


CONFIG = Config()


def get_random_proxy():
    response = requests.get(PROXY_LIST_URL)
    soup = BeautifulSoup(response.content, 'lxml')

    exec(soup.select_one('head script').contents[0])

    proxy_list = []

    for row in soup.select('#ipportlist li'):
        ip = row.text

        port_insertion_js_script = row.select_one('script').contents[0]
        port_insertion_sequence = re.search(r'^document\.write\(":"\+(.*)\)$', port_insertion_js_script).groups()[0]

        local_variables = locals()

        port = ''.join([str(local_variables[digit]) for digit in port_insertion_sequence.split('+')])

        proxy_list.append(f'{ip}:{port}')

    random_proxy = random.choice(proxy_list)

    return random_proxy


def proxy_request(method: str,
                  url: str,
                  headers: dict = None,
                  data: Union[dict, str, bytes, bytearray] = None) -> Union[requests.Response, None]:
    try:
        response = CONFIG.session.request(
            method,
            url,
            headers=headers,
            data=data,
            cookies=CONFIG.cookies,
        )
    except requests.exceptions.ConnectionError:
        print('Ошибка подключения к прокси-серверу')
        sys.exit()

    if response.status_code == 500 or response.url.endswith('page_error.asp'):
        print('Ошибка сервера, попробуйте повторить вход')
        CONFIG.cookies = {}
        authenticate(**prompt_login())
        return proxy_request(method, url, headers=headers, data=data)
    elif response.url.endswith('ip_blocked.asp'):
        print('Данный IP заблокирован на сервисе elibrary.ru')
        sys.exit()

    return response


def authenticate(login: str, password: str):
    response = proxy_request(
        'POST',
        AUTH_URL,
        data={'login': login, 'password': password},
    )

    CONFIG.cookies = response.cookies.get_dict()


def prompt_login() -> Dict[str, str]:
    login = input('Введите имя пользователя: ')
    password = getpass(f'Пароль для {login}: ')

    return {'login': login, 'password': password}


def resolve_author(lastname: str) -> Union[Dict[str, str], None]:
    authors_list = []

    authors_page = proxy_request(
        'POST',
        AUTHOR_LIST_URL,
        headers={
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36',
            'content-type': 'application/x-www-form-urlencoded'
        },
        data={
            'surname': lastname,
            'orgname': 'Санкт-Петербургский государственный университет телекоммуникаций им. проф. М.А. Бонч-Бруевича',
            'orgid': '1193',
            'metrics': '1',
            'order': '0',
            'sortorder': '0',
        },
    )

    authors_soup = BeautifulSoup(authors_page.content, 'lxml')

    authors_row_list = authors_soup.select('#restab tr[valign="top"]')

    if len(authors_row_list) == 0:
        return None

    for author_row in authors_row_list:
        author_name = author_row.select_one('td.midtext[align="left"] > font > b').text.strip()

        while True:
            is_requested_author = input(author_name + '? [Y/n]: ').lower().strip()

            if is_requested_author in ('y', ''):
                author_id = author_row.get('id', '').lstrip('a')

                return {
                    'id': author_id,
                    'name': author_name,
                }
            elif is_requested_author == 'n':
                break


def get_author():
    lastname = input('Введите фамилию автора: ')

    return resolve_author(lastname)


def get_pages_count(url, author):
    page = proxy_request(
        'GET',
        url,
        data={
            'authorid': author['id'],
        },
    )

    soup = BeautifulSoup(page.content, 'lxml')

    try:
        page_count_expression = soup.select('#pages td')[-1].select_one('a').get('href', '')
    except (IndexError, AttributeError, TypeError):
        return 1

    page_count = int(re.search(r'^javascript:goto_page\(([0-9]+)\)$', page_count_expression).groups()[0])

    return page_count


def get_author_items(author):
    page_count = get_pages_count(AUTHOR_ITEMS_URL, author)

    author_items = []

    for page_number in range(1, page_count + 1):
        print(f'Загрузка статей автора (страница {page_number} из {page_count})...')

        items_page = proxy_request(
            'POST',
            AUTHOR_ITEMS_URL,
            data={
                'authorid': author['id'],
                'pagenum': page_number,
            },
        )

        items_soup = BeautifulSoup(items_page.content, 'lxml')

        items_row_list = items_soup.select('#restab tr[valign="middle"]')

        for row in items_row_list:
            author_items.append({
                'id': row.get('id', '').lstrip('arw'),
                'title': row.select_one('td[align="left"] a').text.strip(),
                'authors': row.select_one('td[align="left"] i').text.strip().split(', '),
                'description': row.select('td[align="left"] font')[-1].text.strip(),
            })

    return author_items


def get_author_refs(author):
    page_count = get_pages_count(AUTHOR_REFS_URL, author)

    author_refs = []

    for page_number in range(1, page_count + 1):
        print(f'Загрузка ссылок на статьи автора (страница {page_number} из {page_count})...')

        refs_page = proxy_request(
            'POST',
            AUTHOR_REFS_URL,
            data={
                'authorid': author['id'],
                'pagenum': page_number,
            },
        )

        refs_soup = BeautifulSoup(refs_page.content, 'lxml')

        refs_row_list = refs_soup.select('#restab tr[valign="middle"]')

        for row in refs_row_list:
            author_refs.append({
                'id': row.get('id', '').lstrip('arw'),
                'count_number': row.select_one('td[align="center"] b').text.strip(),
                'source': row.select_one('td[align="left"] > font').text.strip(),
                'cite_item': row.select_one('td[align="left"] table .menug').text.strip(),
                'malformed': row.select_one('td[align="left"] > a') is None,
            })

    return author_refs


if __name__ == '__main__':
    atexit.register(CONFIG.save_cookies)

    CONFIG.session.proxies['http'] = CONFIG.session.proxies['https'] = 'socks5h://localhost:9050'

    # while True:
    #     use_proxy = input('Использовать прокси? [Y/n]: ').lower().strip()
    #
    #     if use_proxy in ('y', ''):
    #         CONFIG.proxies = {'https': input('Введите адрес прокси в формате "<протокол>://<адрес>[:<порт>]": ')}
    #
    #         print(f"Текущий адрес прокси: {CONFIG.proxies['https']}")
    #
    #         break
    #     elif use_proxy == 'n':
    #         break

    if 'SCookieID' not in CONFIG.cookies and 'SUserID' not in CONFIG.cookies:
        authenticate(**prompt_login())

    author = get_author()

    if author is None:
        print('Автора с таким именем не найдено')
        sys.exit()

    items = get_author_items(author)
    refs = get_author_refs(author)

    got_malformed_refs = False

    for ref in refs:
        if ref['malformed']:
            got_malformed_refs = True

            print('\nНайдена неверная ссылка на статью:')
            print('Порядковый номер ссылки в списке ссылок: ' + ref['count_number'])
            print('Название цитируемой статьи:\n' + ref['source'])
            print('Название ссылающейся статьи:\n' + ref['cite_item'])

    if not got_malformed_refs:
        print('Неверных ссылок не найдено')
