from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from db import get_connection
import sqlite3
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone

#Clé secrète pour générer les tokens 
SECRET_KEY = "super_secret_netflix_key" 
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

# Fonction pour vérifier un mot de passe
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def create_access_token(data: dict):
    to_encode = data.copy()
    # Le token expirera dans 2 heures
    expire = datetime.now(timezone.utc) + timedelta(hours=2)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

app = FastAPI()


@app.get("/ping")
def ping():
    return {"message": "pong"}

@app.get("/films")
def get_films():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Film")
        films = cursor.fetchall()
        
        #on convertit chaque objet en dictionnaire
        films_convertis = [dict(film) for film in films]
        
        return films_convertis

@app.get("/film/{id}")
def get_film(id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Requête simplifiée avec une f-string
        cursor.execute(f"SELECT * FROM Film WHERE id = {id}")
        
        film = cursor.fetchone()
        
        if film:
            return dict(film)
        
        return {"erreur": "Film introuvable"}
class Film(BaseModel):
    id: int | None = None
    nom: str
    note: float | None = None
    dateSortie: int
    image: str | None = None
    video: str | None = None
    genreId: int | None = None

class UserRegister(BaseModel):
    email: str
    pseudo: str
    password: str


@app.post("/auth/register")
def register(user: UserRegister):
    #On sécurise le mot de passe avant de le sauvegarder
    hashed_pw = hash_password(user.password)
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            #On insère le nouvel utilisateur
            cursor.execute("""
                INSERT INTO Utilisateur (AdresseMail, Pseudo, MotDePasse)
                VALUES (?, ?, ?)
            """, (user.email, user.pseudo, hashed_pw))
            
            # On récupère l'ID qui vient de lui être attribué
            user_id = cursor.lastrowid
            
        
        token = create_access_token(data={"sub": user.email, "id": user_id})
        
       
        return {
            "access_token": token,
            "token_type": "bearer"
        }
        
    except sqlite3.IntegrityError:
        #se déclenche si l'email existe déjà 
        return {"erreur": "Cet email est déjà utilisé."}
    
# Le modèle pour les données de connexion
class UserLogin(BaseModel):
    email: str
    password: str

@app.post("/auth/login")
def login(user: UserLogin):
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. On cherche l'utilisateur dans la base grâce à son email
        cursor.execute("SELECT * FROM Utilisateur WHERE AdresseMail = ?", (user.email,))
        db_user = cursor.fetchone()
        
        # 2. Si l'email n'existe pas, OU que le mot de passe ne correspond pas au hash
        # (On convertit db_user en dict pour pouvoir lire la colonne 'MotDePasse')
        if not db_user or not verify_password(user.password, dict(db_user)["MotDePasse"]):
            return {"erreur": "Email ou mot de passe incorrect"}
            
        # 3. Si tout est bon, on lui génère un nouveau token (bracelet VIP)
        token = create_access_token(data={"sub": dict(db_user)["AdresseMail"], "id": dict(db_user)["ID"]})
        
        return {
            "access_token": token,
            "token_type": "bearer"
        }

@app.post("/film")
async def createFilm(film : Film):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            INSERT INTO Film (Nom,Note,DateSortie,Image,Video)  
            VALUES('{film.nom}',{film.note},{film.dateSortie},'{film.image}','{film.video}') RETURNING *
            """)
        res = cursor.fetchone()
        print(res)
        return res
    

class PreferenceAdd(BaseModel):
    genre_id: int


@app.post("/preferences", status_code=201)
def add_preference(pref: PreferenceAdd, user_id: int = Depends(get_current_user)):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # On relie l'ID du genre et l'ID de l'utilisateur dans la table Genre_Utilisateur
            cursor.execute("""
                INSERT INTO Genre_Utilisateur (ID_Genre, ID_User)
                VALUES (?, ?)
            """, (pref.genre_id, user_id))
            
            return {"message": "Genre ajouté aux favoris !"}
            
    except sqlite3.IntegrityError:
        return {"erreur": "Ce genre est déjà dans vos favoris ou n'existe pas."}

@app.delete("/preferences/{genre_id}")
def remove_preference(genre_id: int, user_id: int = Depends(get_current_user)):
    with get_connection() as conn:
        cursor = conn.cursor()
        
        
        cursor.execute("""
            DELETE FROM Genre_Utilisateur 
            WHERE ID_Genre = ? AND ID_User = ?
        """, (genre_id, user_id))
        
        
        if cursor.rowcount > 0:
            return {"message": "Genre retiré de vos favoris."}
        else:
            return {"erreur": "Ce genre ne faisait pas partie de vos favoris."}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
