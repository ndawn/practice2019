const puppeteer = require('puppeteer');
const fs = require('fs');
const readline = require('readline');
const getpass = require('getpass');


const PROXY_LIST_URL = 'https://premproxy.com/ru/proxy-by-country/list-ip-port/%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D1%8F-01.htm';
const AUTHOR_LIST_URL = 'https://elibrary.ru/authors.asp';
const AUTHOR_ITEMS_URL = 'https://elibrary.ru/author_items.asp';
const AUTHOR_REFS_URL = 'https://elibrary.ru/author_refs.asp';


const create_read_stream = () => readline.createInterface({
    input: process.stdin,
    output: process.stdout
});


const get_random_proxy = async (browser) => {
    const page = await browser.newPage();
    await page.goto(PROXY_LIST_URL);

    const proxy_list = [];

    await Promise.all([
        page.waitForNavigation(),
        page.select('#xf5', '2')
    ]);

    const address_list = await page.evaluate(() => {
        const rows = document.querySelectorAll('.spy1xx[onmouseover] .spy1x[onmouseover]');
        const list = [];

        for (let row of rows) {
            list.push(row.querySelector('td').innerText);
        }

        return list;
    });

    await page.close();

    return address_list[Math.round(Math.random() * (address_list.length - 1))];
};


const authenticate = async (page, login, password) => {
    await page.goto('https://elibrary.ru/defaultx.asp');

    await page.focus('#login');
    await page.keyboard.type(login);

    await page.focus('#password');
    await page.keyboard.type(password);

    await page.click('input[name="knowme"]');

    const [response] = await Promise.all([
        page.waitForNavigation(),
        page.click('#win_login .butred')
    ]);

    if (response.status() === 500) {
        throw new Error('Данный аккаунт или IP-адрес заблокирован на сервисе elibrary.ru');
    }

    fs.writeFileSync('cookies.json', JSON.stringify(await page.cookies()));
};


const prompt_login = async () => {
    const stream = readline.createInterface({
        input: process.stdin,
        output: process.stdout
    });

    return await new Promise(resolve => {
        stream.question('Введите имя пользователя: ', login => {
            stream.question(`Пароль для ${login}: `, password => {
                resolve({login, password});
            })
        });
    });
};


const resolve_author = async (page, lastname) => {
    await page.goto(AUTHOR_LIST_URL);

    await page.focus('#surname');
    await page.keyboard.type(lastname);
    await page.evaluate(() => {
        document.getElementById('orgname').value = 'Санкт-Петербургский государственный университет телекоммуникаций им. проф. М.А. Бонч-Бруевича';
    });

    await Promise.all([
        page.waitForNavigation(),
        page.click('#show_param .butred')
    ]);

    const author_list = await page.evaluate(() => {
        const author_rows = [];

        const author_row_list = document.querySelectorAll('#restab tr[valign="top"]');

        if (author_row_list.length === 0) {
            return null;
        }

        for (let row of author_row_list) {
            author_rows.push({
                id: row.id.slice(1),
                name: row.querySelector('td.midtext[align="left"] > font').textContent
            });
        }

        return author_rows;
    });

    if (author_list === null) {
        return null;
    }

    for (let author of author_list) {
        while (true) {
            const readStream = create_read_stream();

            const is_requested_author = await new Promise(resolve => {
                readStream.question(`${author.name}? [Y/n]: `, answer => resolve(answer.toLowerCase()))
            });

            if (['y', ''].includes(is_requested_author)) {
                return author;
            } else if (is_requested_author === 'n') {
                break
            }
        }
    }

    return null;
};


const get_author = async (page) => {
    const lastname = await new Promise(resolve => {
        create_read_stream().question('Введите фамилию автора: ', lastname => resolve(lastname));
    });

    return await resolve_author(page, lastname);
};


const get_author_items = async (page, author) => {
    const author_items = [];

    let page_number = 1;

    while (true) {
        await page.goto(`${AUTHOR_ITEMS_URL}?authorid=${author.id}&pagenum=${page_number}`);

        const has_next_page = await page.evaluate(() => {
            const pagination_elements = document.querySelectorAll('#pages td.mouse-hovergr');

            if (pagination_elements.length === 0) {
                return false;
            }

            return pagination_elements[pagination_elements.length - 1].querySelector('font') === null;
        });

        const node_console = console;

        const page_items = await page.evaluate(() => {
            const item_row_list = document.querySelectorAll('#restab tr[valign="middle"]');
            const item_list = [];

            if (item_row_list.length === 0) {
                return null;
            }

            node_console.log(`Загрузка статей автора (страница ${page_number})...`);

            for (let row of item_row_list) {
                const description_elements = row.querySelectorAll('td[align="left"] font');

                item_list.push({
                    id: row.id.slice(3),
                    title: row.querySelector('td[align="left"] a').textContent.trim(),
                    authors: row.querySelector('td[align="left"] i').textContent.trim().split(', '),
                    description: description_elements[description_elements.length - 1].textContent.trim(),
                });
            }

            return item_list;
        });

        if (page_items === null) {
            break;
        }

        author_items.concat(...page_items);

        if (!has_next_page) {
            break;
        }

        page_number++;
    }

    return author_items;
};


const get_author_refs = async (page, author) => {
    const author_refs = [];

    let page_number = 1;

    while (true) {
        await page.goto(`${AUTHOR_REFS_URL}?authorid=${author.id}&pagenum=${page_number}`);

        if ((await page.url()).endsWith('page_error.asp')) {
            throw new Error('Ошибка сервера, попробуйте повторить попытку');
        }

        const has_next_page = await page.evaluate(() => {
            const pagination_elements = document.querySelectorAll('#pages td.mouse-hovergr');

            if (pagination_elements.length === 0) {
                return false;
            }

            return pagination_elements[pagination_elements.length - 1].querySelector('font') === null;
        });

        const node_console = console;

        const page_refs = await page.evaluate(() => {
            const ref_row_list = document.querySelectorAll('#restab tr[valign="middle"]');
            const ref_list = [];

            if (ref_row_list.length === 0) {
                return null;
            }

            node_console.log(`Загрузка ссылок на статьи автора (страница ${page_number})...`);

            for (let row of ref_row_list) {
                ref_list.push({
                    id: row.id.slice(3),
                    count_number: row.querySelector('td[align="center"] b').textContent.trim(),
                    source: row.querySelector('td[align="left"] > font').textContent.trim(),
                    cite_item: row.querySelector('td[align="left"] table .menug').textContent.trim(),
                    malformed: row.querySelector('td[align="left"] > a') === null,
                });
            }

            return ref_list;
        });

        if (page_refs === null) {
            break;
        }

        author_refs.concat(...page_refs);

        if (!has_next_page) {
            break;
        }

        page_number++;
    }

    return author_refs;
};


const main = async () => {
    const browser = await puppeteer.launch({headless: false});
    const page = await browser.newPage();
    await page.goto('https://elibrary.ru/defaultx.asp');

    const cookies = JSON.parse(fs.readFileSync('cookies.json').toString());

    await page.setCookie(...cookies);

    if (!Object.keys(cookies).includes('SCookieID') && !Object.keys(cookies).includes('SUserID')) {
        const credentials = await prompt_login();

        try {
            await authenticate(page, credentials.login, credentials.password);
        } catch (exception) {
            console.log(exception.message);
            process.exit(1);
        }
    }

    const author = await get_author(page);

    if (author === null) {
        console.log('Автора с таким именем не найдено');
        process.exit(0);
    }

    const items = await get_author_items(page, author);
    let refs;

    try {
        refs = await get_author_refs(page, author);
    } catch (exception) {
        console.log(exception.message);
        process.exit(1);
    }

    let got_malformed_refs = false;

    for (let ref of refs) {
        if (ref.malformed) {
            got_malformed_refs = true;

            console.log('\nНайдена неверная ссылка на статью');
            console.log('Порядковый номер ссылки в списке ссылок: ' + ref.count_number);
            console.log('Название цитируемой статьи:\n' + ref.source);
            console.log('Название ссылающейся статьи:\n' + ref.cite_item);
        }
    }

    if (!got_malformed_refs) {
        console.log('Неверных ссылок не найдено');
    }
};


main().then();
