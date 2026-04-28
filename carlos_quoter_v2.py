import docx
import re

def get_prices():
    prices = []
    try:
        with open("full_price_list.txt", "r", encoding="utf-16") as f:
            lines = f.readlines()
    except UnicodeError:
        with open("full_price_list.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    for line in lines:
        line = line.strip()
        if not line: continue
        parts = line.split()
        if len(parts) >= 3:
            p2 = parts[-1].replace('.', '').replace(',', '.')
            p1 = parts[-2].replace('.', '').replace(',', '.')
            try:
                float(p1)
                float(p2)
                desc = " ".join(parts[:-2]).upper()
                prices.append({"desc": desc, "p1": parts[-2], "p2": parts[-1]})
            except ValueError:
                continue
    return prices

def quote_v2():
    prices = get_prices()
    doc = docx.Document("LISTA DE PRECIOS 27-04-26.docx")
    table = doc.tables[0]
    
    # Specific Rule Mappings (Hardcoded based on user feedback)
    rules = {
        "CEFALEXINA 500 MG X 8": "BUTEFINA",
        "CARBAMAZEPINA 200 MG X 10": "CARBAMAZEPINA DENVER FARMA 200MG",
        "DEXAMETASONA 8 MG X 2 ML AMP": "DEXAMETASONA DENVER FARMA 4MG /ML", # Highest price 800,65
        "DEXAMETASONA 0,5  MG X 10": "RUPEDEX",
        "PARACETAMOL 500 MG  X 10": "PARACETAMOL TEVA 500MG",
        "PARACETAMOL 1 GR  X 10": "PARACETAMOL TEVA 1 G",
        "TALDALAFILO 5 MG X 30": "ALMAXIMO 36 5MG"
    }

    for i, row in enumerate(table.rows):
        if i == 0: continue
        item_name = row.cells[1].text.strip().upper()
        if not item_name: continue
        
        found_price = None
        
        # 1. Check specific rules
        for key, pattern in rules.items():
            if key in item_name:
                # Find matching product in list
                for p in prices:
                    if pattern in p["desc"]:
                        found_price = p["p1"]
                        break
                if found_price: break

        # 2. Special case: Jeringa (Descartable) + 21% IVA
        if "JERINGA" in item_name:
            for p in prices:
                if "JERINGA 10 ML" in p["desc"]:
                    val = float(p["p1"].replace('.', '').replace(',', '.'))
                    val_with_iva = val * 1.21
                    found_price = f"{val_with_iva:,.2f}".replace('.', 'X').replace(',', '.').replace('X', ',')
                    break

        # 3. Fuzzy matching for the rest (but more careful)
        if not found_price:
            # Avoid matching random "CREMA X 20" if it doesn't match the name
            if "CALMURID" in item_name or "TRIBIOCORT" in item_name or "OTOLEF" in item_name:
                found_price = "" # Leave blank as requested
            else:
                # Basic fuzzy logic for others
                query_parts = item_name.replace("ATORVASTATIN", "ATORVASTAN").split()
                best_p = None
                max_m = 0
                for p in prices:
                    m = sum(1 for part in query_parts if part in p["desc"])
                    if m > max_m:
                        max_m = m
                        best_p = p["p1"]
                if max_m >= 2: # At least 2 words must match
                    found_price = best_p

        if found_price:
            row.cells[2].text = f"$ {found_price}"
        else:
            row.cells[2].text = ""

    output_path = "COTIZACION PUEYRREDON 27-04-26_V2.docx"
    doc.save(output_path)
    print(f"Saved: {output_path}")

if __name__ == "__main__":
    quote_v2()
