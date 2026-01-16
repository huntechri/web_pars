
import customtkinter as ctk
import threading
import os
import sys
import json
from datetime import datetime
from full_auto_parser_CURL import CurlParser

# Set appearance mode and color theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class CategoryTreeNode:
    """Узел дерева категорий с чекбоксом (БЕЗ API-запросов)"""
    def __init__(self, parent_frame, category_data, level=0, on_change_callback=None):
        self.category_data = category_data
        self.level = level
        self.on_change_callback = on_change_callback
        self.children_nodes = []
        self.is_expanded = False
        
        # Основной контейнер для этого узла
        self.container = ctk.CTkFrame(parent_frame, fg_color="transparent")
        self.container.pack(fill="x", padx=(level * 20, 0), pady=1)
        
        # Строка с чекбоксом и кнопкой раскрытия
        self.header_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.header_frame.pack(fill="x")
        
        # Кнопка раскрытия (если есть дети)
        self.has_children = len(category_data.get('children', [])) > 0
        if self.has_children:
            self.expand_button = ctk.CTkButton(
                self.header_frame, 
                text="▶", 
                width=20, 
                height=20,
                command=self.toggle_expand,
                fg_color="transparent",
                hover_color="#333333"
            )
            self.expand_button.pack(side="left", padx=2)
        else:
            # Пустое место для выравнивания
            spacer = ctk.CTkLabel(self.header_frame, text="  ", width=24)
            spacer.pack(side="left")
        
        # Чекбокс
        product_qty = category_data.get('product_qty', 0)
        qty_text = f" [{product_qty}]" if product_qty > 0 else ""
        label_text = f"{category_data.get('title', 'Unnamed')} ({category_data.get('code', '?')}){qty_text}"
        self.checkbox = ctk.CTkCheckBox(
            self.header_frame,
            text=label_text,
            command=self.on_checkbox_change
        )
        self.checkbox.pack(side="left", fill="x", expand=True)
        
        # Контейнер для дочерних элементов
        self.children_container = ctk.CTkFrame(self.container, fg_color="transparent")
        self.children_loaded = False
    
    def toggle_expand(self):
        """Раскрыть/свернуть дочерние элементы"""
        if not self.is_expanded:
            # Раскрываем
            if not self.children_loaded:
                self.load_children()
            self.children_container.pack(fill="x", pady=(0, 2))
            self.expand_button.configure(text="▼")
            self.is_expanded = True
        else:
            # Сворачиваем
            self.children_container.pack_forget()
            self.expand_button.configure(text="▶")
            self.is_expanded = False
    
    def load_children(self):
        """Загрузить дочерние элементы ИЗ КОНФИГА (без API)"""
        children = self.category_data.get('children', [])
        for child_data in children:
            child_node = CategoryTreeNode(
                self.children_container,
                child_data,
                level=self.level + 1,
                on_change_callback=self.on_change_callback
            )
            self.children_nodes.append(child_node)
        self.children_loaded = True
    
    def on_checkbox_change(self):
        """Обработка изменения состояния чекбокса"""
        if self.on_change_callback:
            self.on_change_callback()
    
    def is_selected(self):
        """Проверка, выбран ли этот узел"""
        return self.checkbox.get() == 1
    
    def set_selected(self, value):
        """Установить состояние чекбокса"""
        if value:
            self.checkbox.select()
        else:
            self.checkbox.deselect()
    
    
    def get_selected_ids(self):
        """Получить ID всех выбранных категорий (умный сбор без дублей)"""
        selected = []
        
        if self.is_selected():
            # Если выбрана родительская категория - возвращаем ТОЛЬКО её ID.
            # В API Петрович товары родителя УЖЕ включают в себя все товары детей.
            # Поэтому запрашивать детей отдельно - значит плодить дубли.
            cat_id = self.category_data.get('code')
            if cat_id:
                selected.append(cat_id)
        else:
            # Если сам родитель не выбран - проверяем, не выбраны ли его дети по отдельности
            for child in self.children_nodes:
                selected.extend(child.get_selected_ids())
        
        return selected
    
    def _collect_all_child_ids_from_data(self):
        """Рекурсивно собрать ID этой категории и всех дочерних из данных"""
        ids = [self.category_data.get('code')]  # Добавляем ID этой категории
        
        # Собираем ID всех дочерних категорий из данных (не из GUI узлов)
        children = self.category_data.get('children', [])
        for child_data in children:
            child_ids = self._collect_child_ids_recursive(child_data)
            ids.extend(child_ids)
        
        return ids
    
    def _collect_child_ids_recursive(self, category_data):
        """Рекурсивный сбор ID из данных категории"""
        ids = [category_data.get('code')]
        
        children = category_data.get('children', [])
        for child in children:
            ids.extend(self._collect_child_ids_recursive(child))
        
        return ids

    
    def get_category_id(self):
        """Получить ID этой категории"""
        return self.category_data.get('code')

class PetrovichApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Парсер Петрович - Fast Edition")
        self.geometry("1200x900")

        # Настройка сетки
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Боковая панель
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(10, weight=1)

        # Загрузка логотипа и иконки
        try:
            from PIL import Image, ImageTk
            logo_path = resource_path("petrovich-logo-png_seeklogo-227851.png")
            if os.path.exists(logo_path):
                pil_img = Image.open(logo_path)
                
                # Установка иконки окна
                icon_img = ImageTk.PhotoImage(pil_img)
                self.iconphoto(False, icon_img)
                
                # Установка логотипа в боковой панели
                my_image = ctk.CTkImage(light_image=pil_img,
                                        dark_image=pil_img,
                                        size=(150, 50))
                self.logo_label = ctk.CTkLabel(self.sidebar_frame, image=my_image, text="")
            else:
                self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="ПАРСЕР\nПЕТРОВИЧ", font=ctk.CTkFont(size=20, weight="bold"))
        except Exception as e:
            self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="ПАРСЕР\nПЕТРОВИЧ", font=ctk.CTkFont(size=20, weight="bold"))
            print(f"Не удалось загрузить логотип: {e}")

        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.limit_label = ctk.CTkLabel(self.sidebar_frame, text="Лимит на категорию:", anchor="w")
        self.limit_label.grid(row=1, column=0, padx=20, pady=(10, 0))
        self.limit_entry = ctk.CTkEntry(self.sidebar_frame, placeholder_text="Все товары")
        self.limit_entry.grid(row=2, column=0, padx=20, pady=(0, 10))

        self.cookie_button = ctk.CTkButton(self.sidebar_frame, text="Настроить Куки", command=self.open_cookie_dialog, 
                                          fg_color="#555555", hover_color="#777777")
        self.cookie_button.grid(row=3, column=0, padx=20, pady=10)
        
        self.save_settings_button = ctk.CTkButton(self.sidebar_frame, text="Сохранить настройки", 
                                                 command=self.save_settings_manual,
                                                 fg_color="#28a745", hover_color="#218838")
        self.save_settings_button.grid(row=4, column=0, padx=20, pady=10)
        
        self.rebuild_tree_button = ctk.CTkButton(self.sidebar_frame, text="Обновить дерево", 
                                                 command=self.rebuild_tree_prompt,
                                                 fg_color="#17a2b8", hover_color="#138496")
        self.rebuild_tree_button.grid(row=5, column=0, padx=20, pady=10)

        self.appearance_mode_label = ctk.CTkLabel(self.sidebar_frame, text="Тема оформления:", anchor="w")
        self.appearance_mode_label.grid(row=11, column=0, padx=20, pady=(10, 0))
        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.sidebar_frame, values=["Light", "Dark", "System"],
                                                                       command=self.change_appearance_mode_event)
        self.appearance_mode_optionemenu.grid(row=12, column=0, padx=20, pady=(10, 20))
        self.appearance_mode_optionemenu.set("Dark")

        # Основной контент
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(2, weight=1)

        # Шапка с кнопками
        self.header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        self.start_button = ctk.CTkButton(self.header_frame, text="ЗАПУСТИТЬ ПАРСИНГ", command=self.start_parsing_event, 
                                         fg_color="#FF6600", hover_color="#E65C00", font=ctk.CTkFont(weight="bold"))
        self.start_button.pack(side="left", padx=10)
        
        self.stop_button = ctk.CTkButton(self.header_frame, text="ОСТАНОВИТЬ", command=self.stop_parsing_event, 
                                         fg_color="#dc3545", hover_color="#c82333", font=ctk.CTkFont(weight="bold"),
                                         state="disabled")
        self.stop_button.pack(side="left", padx=5)

        self.select_all_button = ctk.CTkButton(self.header_frame, text="Выбрать все", command=self.select_all_event, width=100)
        self.select_all_button.pack(side="left", padx=5)

        self.deselect_all_button = ctk.CTkButton(self.header_frame, text="Снять все", command=self.deselect_all_event, width=100)
        self.deselect_all_button.pack(side="left", padx=5)
        
        self.expand_all_button = ctk.CTkButton(self.header_frame, text="Раскрыть все", command=self.expand_all_event, width=100)
        self.expand_all_button.pack(side="left", padx=5)
        
        self.collapse_all_button = ctk.CTkButton(self.header_frame, text="Свернуть все", command=self.collapse_all_event, width=100)
        self.collapse_all_button.pack(side="left", padx=5)

        # --- ВЫБОР К ОЛОНОК ЧЕРЕЗ ВЫПАДАЮЩИЕ СПИСКИ ---
        self.columns_container = ctk.CTkFrame(self.main_frame)
        self.columns_container.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        
        self.column_label = ctk.CTkLabel(self.columns_container, text="Настройка колонок CSV:", font=ctk.CTkFont(weight="bold"))
        self.column_label.pack(side="left", pady=(5, 0), padx=(5, 10))
        
        self.reset_columns_button = ctk.CTkButton(
            self.columns_container, 
            text="Сбросить колонки", 
            command=self.reset_columns_event,
            fg_color="#dc3545", 
            hover_color="#c82333",
            width=140
        )
        self.reset_columns_button.pack(side="left", pady=(5, 0))

        self.columns_list_frame = ctk.CTkScrollableFrame(self.columns_container, height=100, orientation="horizontal")
        self.columns_list_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.column_options_map = {
            'sku (Артикул)': 'article',
            'name (Название)': 'name',
            'unit (Ед. изм.)': 'unit',
            'price (Цена .)': 'price',
            'weight (Вес .)': 'weight',
            'supplier (Петрович)': 'supplier',
            'image (Картинка)': 'image',
            'product_url (Ссылка)': 'url',
            'category1 (Категория 1)': 'level1',
            'category2 (Категория 2)': 'level2',
            'category3 (Категория 3)': 'level3',
            'category4 (Категория 4)': 'level4',
            'supplers (Поставщик)': 'brand',
            '--- Отключено ---': None
        }
        
        self.display_names = list(self.column_options_map.keys())
        self.column_selectors = []
        
        # Создаем 12 слотов
        initial_order = [
            'sku (Артикул)', 'name (Название)', 'unit (Ед. изм.)', 'price (Цена .)', 
            'weight (Вес .)', 'supplers (Поставщик)', 'image (Картинка)', 'product_url (Ссылка)',
            'category1 (Категория 1)', 'category2 (Категория 2)', 'category3 (Категория 3)', '--- Отключено ---'
        ]
        
        # Загрузка сохраненных настроек
        saved_settings = self.load_settings()
        saved_columns = saved_settings.get("columns", [])

        for i in range(12):
            slot_frame = ctk.CTkFrame(self.columns_list_frame, fg_color="transparent")
            slot_frame.pack(side="left", padx=10, pady=5)
            
            ctk.CTkLabel(slot_frame, text=f"Колонка {i+1}", font=ctk.CTkFont(size=11, slant="italic")).pack()
            
            selector = ctk.CTkOptionMenu(slot_frame, values=self.display_names, width=140)
            selector.pack(pady=5)
            
            # Установка значения: приоритет у сохранения, если нет - берем из дефолта
            val_to_set = '--- Отключено ---'
            if i < len(saved_columns):
                val_to_set = saved_columns[i]
            elif i < len(initial_order):
                val_to_set = initial_order[i]
            
            selector.set(val_to_set)
            self.column_selectors.append(selector)
            
            # Подсказки под селекторами
            hint_text = ""
            if "price" in val_to_set.lower() or "weight" in val_to_set.lower():
                hint_text = "Число с точкой"
            elif "sku" in val_to_set.lower():
                hint_text = "ID товара"
            ctk.CTkLabel(slot_frame, text=hint_text, font=ctk.CTkFont(size=10), text_color="gray").pack()

        # Таб-вью для разделения Парсинга и Результатов
        self.tabview = ctk.CTkTabview(self.main_frame)
        self.tabview.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")
        self.tabview.add("Парсинг")
        self.tabview.add("Результаты")
        self.tabview.set("Парсинг")

        # --- ВКЛАДКА ПАРСИНГ ---
        self.tabview.tab("Парсинг").grid_columnconfigure(0, weight=1)
        self.tabview.tab("Парсинг").grid_rowconfigure(0, weight=1)
        
        self.scrollable_frame = ctk.CTkScrollableFrame(self.tabview.tab("Парсинг"), label_text="Категории для сбора данных (быстрая загрузка из конфига)")
        self.scrollable_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        self.category_tree_nodes = []

        # --- ВКЛАДКА РЕЗУЛЬТАТЫ ---
        self.tabview.tab("Результаты").grid_columnconfigure(0, weight=1)
        self.tabview.tab("Результаты").grid_rowconfigure(1, weight=1)

        self.results_header = ctk.CTkFrame(self.tabview.tab("Результаты"), fg_color="transparent")
        self.results_header.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        
        self.refresh_button = ctk.CTkButton(self.results_header, text="Обновить список", command=self.load_files_into_ui, width=120)
        self.refresh_button.pack(side="left", padx=5)
        
        self.open_folder_button = ctk.CTkButton(self.results_header, text="Открыть папку", command=self.open_folder_event, width=120, fg_color="#555555")
        self.open_folder_button.pack(side="left", padx=5)

        self.files_scrollable_frame = ctk.CTkScrollableFrame(self.tabview.tab("Результаты"), label_text="Спарсенные файлы (CSV)")
        self.files_scrollable_frame.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")

        # Окно логов
        self.log_textbox = ctk.CTkTextbox(self.main_frame, height=200, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_textbox.grid(row=3, column=0, padx=10, pady=10, sticky="nsew")
        self.log_textbox.insert("0.0", "Dobro pozhalovat v Petrovich Parser Pro - FAST EDITION!\n")
        self.log_textbox.insert("end", "Derevo kategoriy zagruzhaetsya IZ KONFIGA (mgnovenno).\n")
        self.log_textbox.insert("end", "API ispolzuetsya TOLKO dlya parsinga tovarov.\n\n")
        self.log_textbox.configure(state="disabled")

        # Прогресс-бар
        self.progress_bar = ctk.CTkProgressBar(self.main_frame)
        self.progress_bar.grid(row=4, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.progress_bar.set(0)

        # Инициализация парсера
        self.parser = None
        self.parsing_thread = None
        self.rebuild_thread = None
        
        self.load_categories_tree()
        self.load_files_into_ui()

    def load_categories_tree(self):
        """Загрузка категорий ИЗ JSON КОНФИГА (без API)"""
        try:
            # Проверяем наличие файла с деревом
            tree_file = 'categories_full_tree.json'
            if not os.path.exists(tree_file):
                self.update_log(f"\n[!] Fayl {tree_file} ne nayden!\n")
                self.update_log("Zapustite: python build_full_categories_tree.py\n\n")
                return
            
            # Загружаем дерево из JSON
            with open(tree_file, 'r', encoding='utf-8') as f:
                full_tree = json.load(f)
            
            # Инициализируем парсер (только для парсинга товаров)
            self.parser = CurlParser(log_callback=self.update_log)
            
            # Загружаем сохраненные выборы
            saved_settings = self.load_settings()
            saved_selected = set(saved_settings.get("selected_categories", []))
            
            # Создаем узлы для каждой родительской группы
            for parent_name, cats in full_tree.items():
                # Создаем заголовок группы
                group_label = ctk.CTkLabel(
                    self.scrollable_frame,
                    text=f"═══ {parent_name} ═══",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color="#FF6600"
                )
                group_label.pack(anchor="w", padx=5, pady=(10, 5))
                
                # Создаем узлы дерева из конфига
                for cat_data in cats:
                    tree_node = CategoryTreeNode(
                        self.scrollable_frame,
                        cat_data,
                        level=0,
                        on_change_callback=self.on_category_selection_change
                    )
                    
                    # Восстанавливаем сохраненное состояние
                    if cat_data.get('code') in saved_selected:
                        tree_node.set_selected(True)
                    
                    self.category_tree_nodes.append(tree_node)
            
            self.update_log(f"[OK] Derevo kategoriy zagruzheno iz {tree_file}!\n")
            self.update_log(f"[OK] Kategoriy: {sum(len(cats) for cats in full_tree.values())}\n\n")
            
        except Exception as e:
            self.update_log(f"[ERROR] Oshibka zagruzki dereva: {e}\n")

    def rebuild_tree_prompt(self):
        """Запуск перестроения дерева категорий в отдельном потоке"""
        if self.rebuild_thread and self.rebuild_thread.is_alive():
            self.update_log("\n[!] Obnovlenie dereva uzhe zapusheno!\n")
            return
            
        self.update_log("\n" + "="*50)
        self.update_log("\nZAPUSK OBNOVLENIYA DEREVA KATEGORIY...\n")
        self.update_log("Eto mozhet zanyat 5-10 minut.\n")
        self.update_log("="*50 + "\n")
        
        self.rebuild_tree_button.configure(state="disabled", text="Obnovlyaetsya...")
        self.rebuild_thread = threading.Thread(target=self.run_rebuild_tree_thread)
        self.rebuild_thread.daemon = True
        self.rebuild_thread.start()

    def run_rebuild_tree_thread(self):
        """Поток для запуска внешнего скрипта генерации дерева"""
        import subprocess
        import sys
        try:
            # Запускаем скрипт build_full_categories_tree.py
            cmd = [sys.executable, "build_full_categories_tree.py"]
            
            # Для Windows отключаем окно консоли
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
                
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                encoding='utf-8',
                creationflags=creationflags
            )
            
            for line in process.stdout:
                if line.strip():
                    self.update_log(f"  [TREE] {line}")
            
            process.wait()
            
            if process.returncode == 0:
                self.update_log("\n[OK] DEREVO USPESHNO OBNOVLENO!\n")
                # Перезагружаем интерфейс дерева (в главном потоке)
                self.after(0, self.reload_tree_ui)
            else:
                self.update_log(f"\n[ERROR] Oshibka pri obnovlenii dereva (kod {process.returncode})\n")
                
        except Exception as e:
            self.update_log(f"\n[ERROR] Ne udalos zapustit obnovlenie: {e}\n")
        finally:
            self.after(0, lambda: self.rebuild_tree_button.configure(state="normal", text="Обновить дерево"))

    def reload_tree_ui(self):
        """Полная перезагрузка UI дерева"""
        # Очищаем текущие виджеты
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        
        # Очищаем список узлов
        self.category_tree_nodes = []
        
        # Загружаем заново
        self.load_categories_tree()

    def stop_parsing_event(self):
        """Запрос на остановку парсинга"""
        if self.parser:
            self.update_log("\n[!] OSTANOVKA... Dozhdites zaversheniya tekushikh zaprosov.\n")
            self.parser.stop_requested = True
            self.stop_button.configure(state="disabled", text="Ostanovka...")

    def on_category_selection_change(self):
        """Callback при изменении выбора категорий"""
        # Автосохранение при каждом изменении
        self.after(500, self.save_settings_auto)

    def select_all_event(self):
        for node in self.category_tree_nodes:
            node.set_selected(True)
            for child in node.children_nodes:
                self._select_all_recursive(child)
        self.save_settings_auto()
   
    def _select_all_recursive(self, node):
        node.set_selected(True)
        for child in node.children_nodes:
            self._select_all_recursive(child)

    def deselect_all_event(self):
        for node in self.category_tree_nodes:
            node.set_selected(False)
            for child in node.children_nodes:
                self._deselect_all_recursive(child)
        self.save_settings_auto()
    
    def _deselect_all_recursive(self, node):
        node.set_selected(False)
        for child in node.children_nodes:
            self._deselect_all_recursive(child)
    
    def expand_all_event(self):
        """Раскрыть все категории"""
        for node in self.category_tree_nodes:
            if node.has_children and not node.is_expanded:
                node.toggle_expand()
            self._expand_all_recursive(node)
    
    def _expand_all_recursive(self, node):
        for child in node.children_nodes:
            if child.has_children and not child.is_expanded:
                child.toggle_expand()
            self._expand_all_recursive(child)
    
    def collapse_all_event(self):
        """Свернуть все категории"""
        for node in self.category_tree_nodes:
            if node.is_expanded:
                node.toggle_expand()
    
    def reset_columns_event(self):
        """Сбросить колонки к дефолтным значениям"""
        default_order = [
            'sku (Артикул)', 'name (Название)', 'unit (Ед. изм.)', 'price (Цена .)', 
            'weight (Вес .)', 'supplers (Поставщик)', 'image (Картинка)', 'product_url (Ссылка)',
            'category1 (Категория 1)', 'category2 (Категория 2)', 'category3 (Категория 3)', '--- Отключено ---'
        ]
        
        for i, selector in enumerate(self.column_selectors):
            if i < len(default_order):
                selector.set(default_order[i])
            else:
                selector.set('--- Отключено ---')
        
        self.save_settings_auto()
        self.update_log("[OK] Kolonki sbrosheny k defaultnym znacheniyam!\n")

    def load_files_into_ui(self):
        # Очистка текущего списка
        for widget in self.files_scrollable_frame.winfo_children():
            widget.destroy()

        files = [f for f in os.listdir('.') if f.endswith('.csv') and f.startswith('petrovich_')]
        files.sort(reverse=True) # Свежие сверху

        if not files:
            label = ctk.CTkLabel(self.files_scrollable_frame, text="Файлы не найдены")
            label.pack(pady=20)
            return

        for file in files:
            file_frame = ctk.CTkFrame(self.files_scrollable_frame, fg_color="transparent")
            file_frame.pack(fill="x", padx=5, pady=2)
            
            name_label = ctk.CTkLabel(file_frame, text=file, anchor="w")
            name_label.pack(side="left", padx=10, fill="x", expand=True)
            
            open_btn = ctk.CTkButton(file_frame, text="Открыть", width=80, 
                                     command=lambda f=file: self.open_file_event(f))
            open_btn.pack(side="left", padx=5)
            
            del_btn = ctk.CTkButton(file_frame, text="Удалить", width=80, fg_color="#dc3545", hover_color="#c82333",
                                    command=lambda f=file: self.delete_file_event(f))
            del_btn.pack(side="left", padx=5)

    def open_file_event(self, filename):
        try:
            os.startfile(filename)
        except Exception as e:
            self.update_log(f"Oshibka pri otkrytii fayla: {e}\n")

    def delete_file_event(self, filename):
        try:
            if os.path.exists(filename):
                os.remove(filename)
                self.update_log(f"Fayl udalen: {filename}\n")
                self.load_files_into_ui()
        except Exception as e:
            self.update_log(f"Oshibka pri udalenii fayla: {e}\n")

    def open_folder_event(self):
        try:
            os.startfile('.')
        except Exception as e:
            self.update_log(f"Oshibka pri otkrytii papki: {e}\n")

    def update_log(self, message):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def update_progress(self, value):
        self.progress_bar.set(value)

    def change_appearance_mode_event(self, new_appearance_mode: str):
        ctk.set_appearance_mode(new_appearance_mode)

    def open_cookie_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Nastroyka Kuk")
        dialog.geometry("600x500")
        dialog.attributes("-topmost", True)

        label = ctk.CTkLabel(dialog, text="Vvedite kuki v formate JSON (kak v fayle Cook):", font=ctk.CTkFont(weight="bold"))
        label.pack(pady=10)

        import json
        current_cookies = json.dumps(self.parser.cookies, indent=4, ensure_ascii=False)
        
        textbox = ctk.CTkTextbox(dialog, height=350, font=ctk.CTkFont(family="Consolas", size=12))
        textbox.pack(padx=20, pady=10, fill="both", expand=True)
        textbox.insert("0.0", current_cookies)

        def save_and_close():
            try:
                new_cookies = json.loads(textbox.get("0.0", "end"))
                if self.parser.save_cookies(new_cookies):
                    self.update_log("Kuki uspeshno obnovleny cherez interfeys.\n")
                    dialog.destroy()
                else:
                    self.update_log("Oshibka pri sohranenii kuk.\n")
            except Exception as e:
                self.update_log(f"Oshibka formata JSON: {e}\n")

        save_btn = ctk.CTkButton(dialog, text="Sohranit", command=save_and_close, fg_color="#28a745", hover_color="#218838")
        save_btn.pack(pady=10)

    def load_settings(self):
        try:
            if os.path.exists("settings.json"):
                with open("settings.json", "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"Oshibka zagruzki nastroek: {e}")
        return {}

    def save_settings_auto(self):
        """Автоматическое сохранение настроек"""
        try:
            # Собираем выбранные колонки
            current_cols = [s.get() for s in self.column_selectors]
            
            # Собираем ID выбранных категорий
            selected_ids = []
            for node in self.category_tree_nodes:
                selected_ids.extend(node.get_selected_ids())
            
            settings = {
                "columns": current_cols,
                "selected_categories": selected_ids
            }
            
            with open("settings.json", "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
            
        except Exception as e:
            self.update_log(f"Oshibka avtosohraneniya: {e}\n")
    
    def save_settings_manual(self):
        """Ручное сохранение настроек с уведомлением"""
        self.save_settings_auto()
        self.update_log("[OK] Nastroyki sohranyeny!\n")

    def start_parsing_event(self):
        # Собираем выбранные ID категорий
        selected_ids = []
        for node in self.category_tree_nodes:
            selected_ids.extend(node.get_selected_ids())
        
        if not selected_ids:
            self.update_log("VNIMANIE: Kategorii ne vybrany!\n")
            return

        # Сохраняем настройки перед запуском
        self.save_settings_auto()

        # Собираем колонки (включая пустые/отключенные)
        selected_cols = []
        for selector in self.column_selectors:
            val = selector.get()
            key = self.column_options_map.get(val)
            selected_cols.append(key) # key может быть None
        
        # Проверка: должен быть выбран хотя бы один реальный столбец
        if all(k is None for k in selected_cols):
            self.update_log("VNIMANIE: Ne vybrano ni odnoy kolonki!\n")
            return
        
        # Проверка на дубликаты
        real_cols = [c for c in selected_cols if c is not None]
        if len(real_cols) != len(set(real_cols)):
            self.update_log("[!] VNIMANIE: Obnaruzheny dubliruushiesya kolonki!\n")
            self.update_log("[!] Nazhimite 'Sbrosit kolonki' dlya ispravleniya.\n")
            return

        limit_str = self.limit_entry.get()
        limit = int(limit_str) if limit_str.isdigit() else None

        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal", text="ОСТАНОВИТЬ")
        self.progress_bar.set(0)
        self.update_log(f"\n--- ZAPUSK PARSINGA V {datetime.now().strftime('%H:%M:%S')} ---\n")
        self.update_log(f"Vybrano kategoriy: {len(selected_ids)}\n")
        
        # ДИАГНОСТИКА: показываем ID
        self.update_log(f"ID kategoriy: {', '.join(str(id) for id in selected_ids)}\n")
        
        # Запуск в потоке
        self.parsing_thread = threading.Thread(target=self.run_parser_thread, args=(selected_ids, limit, selected_cols))
        self.parsing_thread.daemon = True
        self.parsing_thread.start()

    def run_parser_thread(self, selected_ids, limit, selected_cols):
        try:
            # Используем уже созданный парсер
            if not self.parser:
                self.parser = CurlParser(log_callback=self.update_log, progress_callback=self.update_progress)
            else:
                self.parser.log_callback = self.update_log
                self.parser.progress_callback = self.update_progress
                self.parser.stop_requested = False
            
            # Используем метод run() парсера с параллельной загрузкой
            self.update_log(f"\nIspolzuem parallelnuyu zagruzku (5 potokov)!\n")
            
            # run() ожидает список ID (строк), передаем их напрямую
            output_file = self.parser.run(
                selected_categories=selected_ids,
                max_products_per_cat=limit,
                selected_columns=selected_cols,
                use_deep_parsing=True,
                parallel=True  # Включаем параллельную загрузку!
            )
            
            if self.parser.stop_requested:
                self.update_log("\n[!] Parsing byl ostanovlen polzovatelem.\n")
            else:
                self.update_log(f"\n[OK] USPEKH! Rezultaty sohranyeny v: {output_file}\n")
            
            self.after(0, self.load_files_into_ui)
            self.after(0, lambda: self.tabview.set("Результаты"))
        except Exception as e:
            self.update_log(f"\nKRITICHESKAYA OSHIBKA: {e}\n")
            import traceback
            self.update_log(traceback.format_exc())
        finally:
            self.after(0, lambda: self.start_button.configure(state="normal"))
            self.after(0, lambda: self.stop_button.configure(state="disabled", text="ОСТАНОВИТЬ"))


if __name__ == "__main__":
    app = PetrovichApp()
    app.mainloop()
