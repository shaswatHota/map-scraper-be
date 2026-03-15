from playwright.sync_api import sync_playwright
import csv
from datetime import datetime
import mysql.connector
from mysql.connector import Error
import re

def create_single_table(cursor, table_name):
    """Create a single table with all fields."""
    create_table_query = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255),
        rating VARCHAR(10),
        reviews VARCHAR(20),
        address TEXT,
        opening VARCHAR(255),
        phone_no VARCHAR(50),
        scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    cursor.execute(create_table_query)


def create_normalized_tables(cursor, base_table_name):
    """Create normalized tables: details and ratings."""
    details_table = f"{base_table_name}_details"
    ratings_table = f"{base_table_name}_ratings"
    
    
    details_query = f"""
    CREATE TABLE IF NOT EXISTS {details_table} (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255),
        address TEXT,
        opening VARCHAR(255),
        phone_no VARCHAR(50),
        scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    cursor.execute(details_query)
    
    
    ratings_query = f"""
    CREATE TABLE IF NOT EXISTS {ratings_table} (
        id INT PRIMARY KEY,
        rating VARCHAR(10),
        reviews VARCHAR(20),
        FOREIGN KEY (id) REFERENCES {details_table}(id) ON DELETE CASCADE
    )
    """
    cursor.execute(ratings_query)
    
    return details_table, ratings_table


def insert_single_table(cursor, table_name, data):
    """Insert data into single table."""
    insert_query = f"""
    INSERT INTO {table_name} (name, rating, reviews, address, opening, phone_no)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    
    for item in data:
        cursor.execute(insert_query, (
            item['Name'],
            item['Rating'],
            item['Reviews'],
            item['Address'],
            item['Opening'],
            item['Phone No']
        ))


def insert_normalized_tables(cursor, details_table, ratings_table, data):
    """Insert data into normalized tables."""
    details_query = f"""
    INSERT INTO {details_table} (name, address, opening, phone_no)
    VALUES (%s, %s, %s, %s)
    """
    
    ratings_query = f"""
    INSERT INTO {ratings_table} (id, rating, reviews)
    VALUES (%s, %s, %s)
    """
    
    for item in data:
        
        cursor.execute(details_query, (
            item['Name'],
            item['Address'],
            item['Opening'],
            item['Phone No']
        ))
        
        
        detail_id = cursor.lastrowid
        
        
        cursor.execute(ratings_query, (
            detail_id,
            item['Rating'],
            item['Reviews']
        ))


def check_table_exists(cursor, table_name):
    """Check if a table exists in the current database."""
    cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
    return cursor.fetchone() is not None


def get_next_table_name(cursor, base_table_name):
    """Find the next available table name with suffix."""
    counter = 1
    while True:
        new_name = f"{base_table_name}{counter}"
        if not check_table_exists(cursor, new_name):
            return new_name
        counter += 1


def get_existing_data(cursor, table_name, is_normalized=False):
    """Fetch all existing data from table as a set of tuples for comparison."""
    if is_normalized:
        
        details_table = table_name
        query = f"SELECT name, address, phone_no FROM {details_table}"
    else:
        query = f"SELECT name, address, phone_no FROM {table_name}"
    
    cursor.execute(query)
    return set(cursor.fetchall())


def save_to_mysql(data, query, db_config):
    """
    Saves scraped data to MySQL database.
    
    Args:
        data: List of dictionaries containing scraped data
        query: The search query used (for table naming)
        db_config: Dictionary with MySQL connection details
    """
    if not data:
        print("No data to save to database.")
        return
    
    connection = None
    cursor = None
    try:
        
        connection = mysql.connector.connect(
            host=db_config['host'],
            user=db_config['user'],
            password=db_config['password']
        )
        
        if connection.is_connected():
            cursor = connection.cursor()
            
            
            cursor.execute("CREATE DATABASE IF NOT EXISTS mapScrape")
            cursor.execute("USE mapScrape")
            print("Connected to database 'mapScrape'")
            

            base_table_name = re.sub(r'[^a-zA-Z0-9_]', '_', query.replace(' ', '_'))
            base_table_name = re.sub(r'_+', '_', base_table_name).strip('_')  
            
            
            print("\nDatabase Structure Options:")
            print("  1 - Single table (all data together)")
            print("  2 - Two tables (details + ratings, normalized)")
            
            structure_choice = input("\nChoose structure (1/2): ").strip()
            
            if structure_choice not in ['1', '2']:
                print("❌ Invalid choice. Defaulting to single table (1).")
                structure_choice = '1'
            
            is_normalized = (structure_choice == '2')
            table_name = base_table_name
            
            
            if is_normalized:
                details_table = f"{base_table_name}_details"
                ratings_table = f"{base_table_name}_ratings"
                table_exists = check_table_exists(cursor, details_table)
                display_name = f"{details_table} & {ratings_table}"
            else:
                table_exists = check_table_exists(cursor, table_name)
                display_name = table_name
            
            if table_exists:
                print(f"\n⚠️  Table '{display_name}' already exists!")
                print("Options:")
                if is_normalized:
                    print(f"  y - Create new tables with suffix (e.g., {base_table_name}_details_1)")
                else:
                    print(f"  y - Create new table with suffix (e.g., {table_name}_1)")
                print("  n - Update existing table (add new rows only)")
                
                choice = input("\nYour choice (y/n): ").strip().lower()
                
                if choice == 'y':
                    
                    if is_normalized:
                        base_table_name = get_next_table_name(cursor, base_table_name + "_details").replace("_details", "")
                        details_table = f"{base_table_name}_details"
                        ratings_table = f"{base_table_name}_ratings"
                        print(f"✓ Creating new tables: '{details_table}' & '{ratings_table}'")
                    else:
                        table_name = get_next_table_name(cursor, base_table_name)
                        print(f"✓ Creating new table: '{table_name}'")
                elif choice == 'n':
                    
                    print(f"✓ Updating existing table: '{display_name}'")
                    
                    
                    check_table = details_table if is_normalized else table_name
                    existing_data = get_existing_data(cursor, check_table, is_normalized)
                    
                    
                    new_data = []
                    duplicate_count = 0
                    for item in data:
                        item_tuple = (item['Name'], item['Address'], item['Phone No'])
                        if item_tuple not in existing_data:
                            new_data.append(item)
                        else:
                            duplicate_count += 1
                    
                    if duplicate_count > 0:
                        print(f"Skipping {duplicate_count} duplicate record(s)")
                    
                    if not new_data:
                        print("✓ No new data to add. All records already exist.")
                        return
                    
                    data = new_data
                    print(f"✓ Adding {len(data)} new record(s)")
                else:
                    print("❌ Invalid choice. Aborting save to database.")
                    return
            
            
            if is_normalized:
                create_normalized_tables(cursor, base_table_name)
                print(f"✓ Created normalized tables: '{details_table}' & '{ratings_table}'")
            else:
                create_single_table(cursor, table_name)
                print(f"✓ Table '{table_name}' is ready")
            
            
            if is_normalized:
                insert_normalized_tables(cursor, details_table, ratings_table, data)
            else:
                insert_single_table(cursor, table_name, data)
            
            connection.commit()
            print(f"✅ Successfully inserted {len(data)} records")
            
            
            if is_normalized:
                print(f"\n📋 Data saved in normalized structure:")
                print(f"   • {details_table} (name, address, opening, phone_no)")
                print(f"   • {ratings_table} (rating, reviews)")
                print(f"   • Relationship: {ratings_table}.id → {details_table}.id (Foreign Key)")
            else:
                print(f"\n📋 Data saved in single table: {table_name}")
            
    except Error as e:
        print(f"Error while connecting to MySQL: {e}")
        print("\nTroubleshooting tips:")
        print("1. Make sure MySQL server is running")
        print("2. Check your credentials (host, user, password)")
        print("3. Verify MySQL is listening on port 3306")
    
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
            print("MySQL connection closed")


def scrape_google_maps(query, scrape_count, save_to_db=False, db_config=None):
    """
    Scrapes Google Maps for a given query with auto-scrolling and a scrape toggler.

    Args:
        query (str): The search query (e.g., 'cafe near Bhubaneswar').
        scrape_count (int or str): The number of listings to scrape, or 'full' to scrape all.
        save_to_db (bool): Whether to save data to MySQL database.
        db_config (dict): MySQL connection config with keys: host, user, password.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)
        page = browser.new_page()
        print('--------------opening google maps-------------------')
        page.goto('https://www.google.com/maps', timeout=60000)

        print('--------------searching your query------------------')
        page.fill('input#searchboxinput', query)
        page.click('button[aria-label="Search"]')
        page.wait_for_timeout(5000) 

        
        scrollable_div = page.locator('div[role="feed"]').first
        if not scrollable_div.is_visible():
             
            scrollable_div = page.locator('div[role="region"]').nth(1)


        
        if scrape_count == 'full':
            print("--------------scrolling to load all results-------------------")
            last_count = 0
            time_stuck = 0
            max_stuck_time = 15
            
            while True:
                
                scrollable_div.evaluate('(element) => element.scrollTop = element.scrollHeight')
                
                page.wait_for_timeout(2000)
                
                new_count = len(page.query_selector_all('a.hfpxzc'))
                print(f"Found {new_count} listings so far...")

                
                if new_count == last_count:
                    time_stuck += 2  
                    print(f"No new results for {time_stuck} seconds...")
                    
                    if time_stuck >= max_stuck_time:
                        print("--------------finished scrolling (no more new results for 15 seconds)-------------------")
                        break
                else:
                    
                    time_stuck = 0
                    last_count = new_count
        else:
            print(f"--------------scrolling to load at least {scrape_count} results-------------------")
            last_count = 0
            time_stuck = 0
            max_stuck_time = 15  
            
            while len(page.query_selector_all('a.hfpxzc')) < scrape_count:
                current_count = len(page.query_selector_all('a.hfpxzc'))
                
                
                scrollable_div.evaluate('(element) => element.scrollTop = element.scrollHeight')
                page.wait_for_timeout(2000)
                
                new_count = len(page.query_selector_all('a.hfpxzc'))
                print(f"Found {new_count} listings so far...")
                
                
                if new_count == last_count:
                    time_stuck += 2  
                    print(f"No new results for {time_stuck} seconds...")
                    
                    if time_stuck >= max_stuck_time:
                        print("--------------finished scrolling (no more new results for 15 seconds)-------------------")
                        break
                else:
                    
                    time_stuck = 0
                    last_count = new_count
        


        print("searching for all hfpxzc <a> tags...\n")
        page.wait_for_selector("a.hfpxzc")
        listings = page.query_selector_all('a.hfpxzc')
        print(f"found {len(listings)} cafes\n")

        result = []
        
        
        num_to_scrape = len(listings) if scrape_count == 'full' else min(scrape_count, len(listings))

        for i in range(num_to_scrape):
            print(f" Scrapping #{i+1}\n")
            listings[i].click()
            page.wait_for_timeout(3000)
            try:
                name = page.inner_text("h1.DUwDvf.lfPIob")
                
                
                try:
                    rating_element = page.locator('span.ceNzKf[role="img"]').first
                    rating_label = rating_element.get_attribute('aria-label', timeout=3000)
                    rating = rating_label.split()[0] if rating_label else "Rating not found"
                except Exception:
                    rating = "Rating not found"
                
                
                try:
                    reviews_element = page.locator('span[aria-label*="reviews"]').first
                    reviews_label = reviews_element.get_attribute('aria-label', timeout=3000)
                    reviews = reviews_label.split()[0] if reviews_label else "Reviews not found"
                except Exception:
                    reviews = "Reviews not found"
                
                
                address_element = page.locator('button[data-item-id="address"]').first
                address = address_element.get_attribute('aria-label').replace('Address:', '').strip() if address_element.is_visible() else "Address not found."

                
                try:
                     opening_element = page.locator("li.G8aQO").first
                     opening = opening_element.inner_text(timeout=3000)  
                     
                     opening = opening.replace('\u202f', ' ')
                except Exception:
                    opening = "Opening hours not found."

                
                try:
                    phone_element = page.locator('button[data-item-id^="phone:tel:"]').first
                    phone_no = phone_element.get_attribute('aria-label', timeout=3000).replace('Phone:', '').strip()
                except Exception:
                    phone_no = "Phone number not found."

                cafe_data = {
                    "Name": name.strip(),
                    "Rating": rating,
                    "Reviews": reviews,
                    "Address": address,
                    "Opening": opening,
                    "Phone No": phone_no
                }
                result.append(cafe_data)
                print(cafe_data)

            except Exception as e:
                print(f"Failed to extract cafe #{i + 1}: {e}")
        
        print("\n--------------scrapping complete-------------------")
        
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"google_maps_scrape_{timestamp}.csv"
        
        if result:
            keys = result[0].keys()
            with open(filename, 'w', newline='', encoding='utf-8') as output_file:
                dict_writer = csv.DictWriter(output_file, fieldnames=keys)
                dict_writer.writeheader()
                dict_writer.writerows(result)
            print(f"Data saved to {filename}")
        
        
        if save_to_db and db_config:
            save_to_mysql(result, query, db_config)
        
        print("Scraped Data:")
        for item in result:
            print(item)
            
        browser.close()
        
        return result, filename

if __name__ == "__main__":
    
    db_config = {
        'host': 'localhost',
        'user': 'mapScrape',  
        'password': 'sh@sw@t12'  
    }
    


    scrape_google_maps(
        query='cafe near Delhi', 
        scrape_count=10,
        save_to_db=True,  
        db_config=db_config
    )

