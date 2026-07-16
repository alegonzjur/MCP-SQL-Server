import os
os.environ["DB_URL"] = "sqlite:///C:/Users/HP/Desktop/Proyectos/MarvelIntelligenceAssistant/data/processed/marvel.db"

import server as s

print(s.list_tables())
print(s.describe_table("cast_members"))
print(s.run_query("SELECT * FROM cast_members LIMIT 5"))
