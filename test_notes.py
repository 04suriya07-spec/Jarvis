import asyncio
from skills.notes import NotesSkill

async def main():
    print("Testing Notes Persistence...")
    ns = NotesSkill()
    print("Creating note...")
    res = await ns.run("create", title="Employee Test", content="Javris is now an employee.", tags=["system"])
    print(res)
    assert res["success"] is True
    
    print("\nListing notes...")
    notes = await ns.run("list")
    for n in notes:
        print(f" - {n['title']} : {n['content']}")
    
    print("\nDONE.")

asyncio.run(main())
