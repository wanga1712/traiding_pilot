# Исправление проблемы с интерпретатором Python в PyCharm

## Проблема

PyCharm использует виртуальное окружение из другого проекта (`pythonProject`), которое ссылается на несуществующий Python 3.9.

## Решение: Настройка интерпретатора через UI PyCharm

### Шаг 1: Открыть настройки интерпретатора

1. Откройте PyCharm
2. Перейдите в **File → Settings** (или нажмите **Ctrl+Alt+S**)
3. В левом меню выберите: **Project: Trading_bot → Python Interpreter**

### Шаг 2: Выбрать правильный интерпретатор

**Вариант A: Если интерпретатор уже есть в списке**

1. В выпадающем списке "Python Interpreter" найдите и выберите:
   ```
   Python 3.13.3 (Trading_bot) [C:\Users\wangr\PycharmProjects\Trading_bot\venv\Scripts\python.exe]
   ```

**Вариант B: Если интерпретатора нет в списке**

1. Нажмите на выпадающий список "Python Interpreter"
2. Выберите **Show All...**
3. Нажмите **+** (Add) в левом верхнем углу
4. Выберите **Existing environment**
5. В поле "Interpreter" укажите путь:
   ```
   C:\Users\wangr\PycharmProjects\Trading_bot\venv\Scripts\python.exe
   ```
6. Нажмите **OK**
7. Убедитесь, что выбран правильный интерпретатор в списке
8. Нажмите **Apply** и **OK**

### Шаг 3: Проверка

После настройки:

1. Внизу справа в PyCharm должно быть указано: `Python 3.13.3 (venv)`
2. Или откройте терминал в PyCharm (Alt+F12) и выполните:
   ```cmd
   python --version
   ```
   Должно показать: `Python 3.13.3`

### Шаг 4: Обновление конфигурации запуска

1. В верхней панели PyCharm найдите выпадающий список с конфигурациями запуска (рядом с кнопкой Run)
2. Выберите конфигурацию **main**
3. Если конфигурации нет, создайте её:
   - Нажмите на выпадающий список конфигураций
   - Выберите **Edit Configurations...**
   - Нажмите **+** → **Python**
   - Название: `main`
   - Script path: `C:\Users\wangr\PycharmProjects\Trading_bot\main.py`
   - Python interpreter: выберите `Python 3.13.3 (Trading_bot)`
   - Нажмите **OK**

## Альтернативное решение: Использование скрипта run.bat

Если настройка через UI не помогает, используйте скрипт `run.bat`:

1. Дважды кликните на файл `run.bat` в корне проекта
2. Или запустите из командной строки:
   ```cmd
   cd C:\Users\wangr\PycharmProjects\Trading_bot
   run.bat
   ```

## Альтернативное решение: Запуск через терминал PyCharm

1. Откройте терминал в PyCharm (Alt+F12)
2. Активируйте виртуальное окружение:
   ```cmd
   venv\Scripts\activate
   ```
3. Запустите приложение:
   ```cmd
   python main.py
   ```

## Что было исправлено автоматически

Я уже исправил файл `.idea/workspace.xml`, изменив путь к интерпретатору в конфигурации запуска `main`:
- Было: `C:\Users\wangr\PycharmProjects\pythonProject\venv\Scripts\python.exe`
- Стало: `C:\Users\wangr\PycharmProjects\Trading_bot\venv\Scripts\python.exe`

Однако PyCharm может перезаписать эти изменения, поэтому **рекомендуется настроить интерпретатор через UI** (Шаг 1-2 выше).

## Проверка установленных зависимостей

Убедитесь, что все зависимости установлены в правильном виртуальном окружении:

```cmd
cd C:\Users\wangr\PycharmProjects\Trading_bot
venv\Scripts\activate
pip list
```

Должны быть установлены:
- PyQt5
- yfinance
- ccxt
- pandas
- matplotlib
- mplfinance
- и другие зависимости из requirements.txt

Если чего-то не хватает:
```cmd
pip install -r requirements.txt
```

