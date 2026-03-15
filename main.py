from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from playwright.async_api import async_playwright
import csv
from datetime import datetime
import mysql.connector
from mysql.connector import Error
import re
import asyncio
from enum import Enum
import os
from pathlib import Path

app = FastAPI(
    title="Google Maps Scraper API",
    description="API for scraping Google Maps listings and storing them in MySQL",
    version="1.0.0"
)

# Create downloads directory if it doesn't exist
DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== Models ====================

class DatabaseStructure(str, Enum):
    SINGLE = "single"
    NORMALIZED = "normalized"

class TableAction(str, Enum):
    CREATE_NEW = "create_new"
    UPDATE_EXISTING = "update_existing"

class DatabaseConfig(BaseModel):
    host: str = "localhost"
    user: str
    password: str
    database: str = "mapScrape"

class ScrapeRequest(BaseModel):
    query: str = Field(..., description="Search query (e.g., 'cafe near Bhubaneswar')")
    scrape_count: int | str = Field(..., description="Number of listings to scrape or 'full' for all")
    save_to_db: bool = Field(default=False, description="Whether to save to database")
    db_config: Optional[DatabaseConfig] = None
    db_structure: DatabaseStructure = Field(default=DatabaseStructure.SINGLE, description="Database structure type")
    table_action: TableAction = Field(default=TableAction.CREATE_NEW, description="Action if table exists")
    headless: bool = Field(default=True, description="Run browser in headless mode (developer option)")

class ScrapedListing(BaseModel):
    name: str
    rating: str
    reviews: str
    address: str
    opening: str
    phone_no: str

class ScrapeResponse(BaseModel):
    success: bool
    message: str
    total_scraped: int
    data: List[ScrapedListing]
    csv_filename: Optional[str] = None
    db_saved: bool = False
    db_table_name: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    timestamp: str

# ==================== Database Functions ====================

def create_single_table(cursor, table_name: str):
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

def create_normalized_tables(cursor, base_table_name: str):
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

def insert_single_table(cursor, table_name: str, data: List[Dict]):
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

def insert_normalized_tables(cursor, details_table: str, ratings_table: str, data: List[Dict]):
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

def check_table_exists(cursor, table_name: str) -> bool:
    """Check if a table exists in the current database."""
    cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
    return cursor.fetchone() is not None

def get_next_table_name(cursor, base_table_name: str) -> str:
    """Find the next available table name with suffix."""
    counter = 1
    while True:
        new_name = f"{base_table_name}{counter}"
        if not check_table_exists(cursor, new_name):
            return new_name
        counter += 1

def get_existing_data(cursor, table_name: str, is_normalized: bool = False):
    """Fetch all existing data from table as a set of tuples for comparison."""
    if is_normalized:
        query = f"SELECT name, address, phone_no FROM {table_name}"
    else:
        query = f"SELECT name, address, phone_no FROM {table_name}"
    
    cursor.execute(query)
    return set(cursor.fetchall())

def save_to_mysql(data: List[Dict], query: str, db_config: DatabaseConfig, 
                  structure: DatabaseStructure, action: TableAction) -> Dict[str, Any]:
    """
    Saves scraped data to MySQL database.
    
    Returns dict with keys: success, message, table_name
    """
    if not data:
        return {"success": False, "message": "No data to save", "table_name": None}
    
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(
            host=db_config.host,
            user=db_config.user,
            password=db_config.password
        )
        
        if connection.is_connected():
            cursor = connection.cursor()
            
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_config.database}")
            cursor.execute(f"USE {db_config.database}")
            
            base_table_name = re.sub(r'[^a-zA-Z0-9_]', '_', query.replace(' ', '_'))
            base_table_name = re.sub(r'_+', '_', base_table_name).strip('_')
            
            is_normalized = (structure == DatabaseStructure.NORMALIZED)
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
                if action == TableAction.CREATE_NEW:
                    if is_normalized:
                        base_table_name = get_next_table_name(cursor, base_table_name + "_details").replace("_details", "")
                        details_table = f"{base_table_name}_details"
                        ratings_table = f"{base_table_name}_ratings"
                    else:
                        table_name = get_next_table_name(cursor, base_table_name)
                elif action == TableAction.UPDATE_EXISTING:
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
                    
                    if not new_data:
                        return {
                            "success": True,
                            "message": f"No new data to add. All {len(data)} records already exist.",
                            "table_name": display_name
                        }
                    
                    data = new_data
            
            if is_normalized:
                create_normalized_tables(cursor, base_table_name)
                insert_normalized_tables(cursor, details_table, ratings_table, data)
                final_table_name = f"{details_table} & {ratings_table}"
            else:
                create_single_table(cursor, table_name)
                insert_single_table(cursor, table_name, data)
                final_table_name = table_name
            
            connection.commit()
            
            return {
                "success": True,
                "message": f"Successfully inserted {len(data)} records",
                "table_name": final_table_name
            }
            
    except Error as e:
        return {
            "success": False,
            "message": f"Database error: {str(e)}",
            "table_name": None
        }
    
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

# ==================== Scraping Functions ====================

async def scrape_google_maps(query: str, scrape_count: int | str) -> tuple[List[Dict], str]:
    """
    Scrapes Google Maps for a given query with auto-scrolling.
    
    Returns: (scraped_data, csv_filename)
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto('https://www.google.com/maps', timeout=60000)
        await page.fill('input#searchboxinput', query)
        await page.click('button[aria-label="Search"]')
        await page.wait_for_timeout(5000)
        
        scrollable_div = page.locator('div[role="feed"]').first
        if not await scrollable_div.is_visible():
            scrollable_div = page.locator('div[role="region"]').nth(1)
        
        if scrape_count == 'full':
            last_count = 0
            time_stuck = 0
            max_stuck_time = 15
            
            while True:
                await scrollable_div.evaluate('(element) => element.scrollTop = element.scrollHeight')
                await page.wait_for_timeout(2000)
                
                new_count = len(await page.query_selector_all('a.hfpxzc'))
                
                if new_count == last_count:
                    time_stuck += 2
                    if time_stuck >= max_stuck_time:
                        break
                else:
                    time_stuck = 0
                    last_count = new_count
        else:
            last_count = 0
            time_stuck = 0
            max_stuck_time = 15
            
            while len(await page.query_selector_all('a.hfpxzc')) < scrape_count:
                await scrollable_div.evaluate('(element) => element.scrollTop = element.scrollHeight')
                await page.wait_for_timeout(2000)
                
                new_count = len(await page.query_selector_all('a.hfpxzc'))
                
                if new_count == last_count:
                    time_stuck += 2
                    if time_stuck >= max_stuck_time:
                        break
                else:
                    time_stuck = 0
                    last_count = new_count
        
        await page.wait_for_selector("a.hfpxzc")
        listings = await page.query_selector_all('a.hfpxzc')
        
        result = []
        num_to_scrape = len(listings) if scrape_count == 'full' else min(int(scrape_count), len(listings))
        
        for i in range(num_to_scrape):
            await listings[i].click()
            await page.wait_for_timeout(3000)
            
            try:
                name = await page.inner_text("h1.DUwDvf.lfPIob")
                
                try:
                    rating_element = page.locator('span.ceNzKf[role="img"]').first
                    rating_label = await rating_element.get_attribute('aria-label', timeout=3000)
                    rating = rating_label.split()[0] if rating_label else "Rating not found"
                except Exception:
                    rating = "Rating not found"
                
                try:
                    reviews_element = page.locator('span[aria-label*="reviews"]').first
                    reviews_label = await reviews_element.get_attribute('aria-label', timeout=3000)
                    reviews = reviews_label.split()[0] if reviews_label else "Reviews not found"
                except Exception:
                    reviews = "Reviews not found"
                
                address_element = page.locator('button[data-item-id="address"]').first
                if await address_element.is_visible():
                    address = (await address_element.get_attribute('aria-label')).replace('Address:', '').strip()
                else:
                    address = "Address not found."
                
                try:
                    opening_element = page.locator("li.G8aQO").first
                    opening = await opening_element.inner_text(timeout=3000)
                    opening = opening.replace('\u202f', ' ')
                except Exception:
                    opening = "Opening hours not found."
                
                try:
                    phone_element = page.locator('button[data-item-id^="phone:tel:"]').first
                    phone_no = (await phone_element.get_attribute('aria-label', timeout=3000)).replace('Phone:', '').strip()
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
                
            except Exception as e:
                print(f"Failed to extract listing #{i + 1}: {e}")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"google_maps_scrape_{timestamp}.csv"
        filepath = DOWNLOADS_DIR / filename
        
        if result:
            keys = result[0].keys()
            with open(filepath, 'w', newline='', encoding='utf-8') as output_file:
                dict_writer = csv.DictWriter(output_file, fieldnames=keys)
                dict_writer.writeheader()
                dict_writer.writerows(result)
        
        await browser.close()
        
        return result, filename

# ==================== API Endpoints ====================

@app.get("/", response_model=HealthResponse)
async def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/scrape", response_model=ScrapeResponse)
async def scrape_maps(request: ScrapeRequest):
    """
    Scrape Google Maps listings based on query.
    
    - **query**: Search query (e.g., 'cafe near Bhubaneswar')
    - **scrape_count**: Number of listings to scrape or 'full' for all
    - **save_to_db**: Whether to save to database
    - **db_config**: Database configuration (required if save_to_db is True)
    - **db_structure**: Database structure type ('single' or 'normalized')
    - **table_action**: Action if table exists ('create_new' or 'update_existing')
    """
    try:
        if request.save_to_db and not request.db_config:
            raise HTTPException(
                status_code=400,
                detail="Database configuration is required when save_to_db is True"
            )
        
        scraped_data, csv_filename = await scrape_google_maps(
            query=request.query,
            scrape_count=request.scrape_count
        )
        
        db_saved = False
        db_table_name = None
        
        if request.save_to_db and request.db_config:
            db_result = save_to_mysql(
                data=scraped_data,
                query=request.query,
                db_config=request.db_config,
                structure=request.db_structure,
                action=request.table_action
            )
            db_saved = db_result["success"]
            db_table_name = db_result["table_name"]
            
            if not db_saved:
                print(f"Database save warning: {db_result['message']}")
        
        listings = [
            ScrapedListing(
                name=item["Name"],
                rating=item["Rating"],
                reviews=item["Reviews"],
                address=item["Address"],
                opening=item["Opening"],
                phone_no=item["Phone No"]
            )
            for item in scraped_data
        ]
        
        return ScrapeResponse(
            success=True,
            message="Scraping completed successfully",
            total_scraped=len(scraped_data),
            data=listings,
            csv_filename=csv_filename,
            db_saved=db_saved,
            db_table_name=db_table_name
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

@app.post("/scrape-background")
async def scrape_maps_background(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """
    Scrape Google Maps listings in the background.
    Returns immediately with a task ID.
    """
    task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    async def scraping_task():
        try:
            scraped_data, csv_filename = await scrape_google_maps(
                query=request.query,
                scrape_count=request.scrape_count
            )
            
            if request.save_to_db and request.db_config:
                save_to_mysql(
                    data=scraped_data,
                    query=request.query,
                    db_config=request.db_config,
                    structure=request.db_structure,
                    action=request.table_action
                )
            
            print(f"Background task {task_id} completed: {len(scraped_data)} records scraped")
        except Exception as e:
            print(f"Background task {task_id} failed: {str(e)}")
    
    background_tasks.add_task(scraping_task)
    
    return {
        "task_id": task_id,
        "status": "started",
        "message": "Scraping task started in background"
    }

@app.get("/download/{filename}")
async def download_csv(filename: str):
    """
    Download a CSV file by filename.
    
    - **filename**: The CSV filename (e.g., 'google_maps_scrape_20251030_103045.csv')
    """
    filepath = DOWNLOADS_DIR / filename
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=filepath,
        media_type='text/csv',
        filename=filename
    )

@app.get("/files")
async def list_files():
    """
    List all available CSV files in the downloads directory.
    """
    files = []
    for file in DOWNLOADS_DIR.glob("*.csv"):
        stat = file.stat()
        files.append({
            "filename": file.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "download_url": f"/download/{file.name}"
        })
    
    return {
        "total_files": len(files),
        "files": sorted(files, key=lambda x: x["created_at"], reverse=True)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)