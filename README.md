# Candilicious

Candilicious Study Bot is a Discord bot designed to help study sessions manage study sessions, track their progress, and engage in fun activities. It aims to restore student freedom in learning unlike the methods of traditional education system.

---

## Features  

- **Study Session Management**  
    - Configure study channels for servers.  
    - Monitor user activity in study voice channels.  
    - Automatically track time spent studying.  
    - Issue warnings for inactivity and disconnect users if necessary.  

- **Leaderboards (Available Soon)**
    - View local leaderboards for within the server
    - View a global leaderboard for all the users over all servers. 

- **Fun Commands**  
    - Play meme songs in Voice channels
    - Play meme sound effects in Voice channels

- **Handling Exception Scenarios**  
    - Allow users with poor network conditions to request temporary exceptions where 5 minutes of relief will be alloted for them.  

- **Data Management**  
    - The bot also helps with user to manage his own data.
    - If its configured on server even that data can be managed.

---
## Docker Based Fast Run
After installing the docker, you can go into the docker shell and just run the following commands to get the bot up and running in no time.  

### Run
```bash
docker run --env-file .env -p 10000:10000 wuiiidocker/candilicious
```
Here `.env` is your environment secret file. Please keep that in the same folder from where this command is being run.

---

## Installation  

1. Clone the repository:  
     ```bash  
     git clone https://github.com/WuiiiGithub/Candilicious.git  
     cd Candilicious  
     ```  

2. Install dependencies:  
     ```bash  
     pip install -r requirements.txt  
     ```  

3. Set up environment variables:  
     - Create a `.env` file in the root directory.  
     - Add the following variables:  
         ```env  
         DB_NAME=Candilicious[Beta]  
         TOKEN=YOUR_DISCORD_BOT_TOKEN  
         MONGODB_URI=YOUR_MONGODB_CONNECTION_STRING  
         FLASK_DOMAIN=http://localhost:10000  
         SECRET_KEY=YOUR_SECRET_KEY  
         ```  

4. Run the bot:  
     ```bash  
     python main.py  
     ```  
---

## Usage  

### Commands  

#### Study Commands  
- `/config <study_channel>`: Configure the study channel for your server.  
- `/leaderboard <scope>`: View the study leaderboard (local or global).  
- `/exception`: Request a temporary exception for poor network conditions.  
- `/delete <scope>`: Delete user or server data.  

#### Fun Commands  
- `/plays <sound>`: Play meme songs in a voice channel.  
- `/playeff <sound>`: Play meme sound effects in a voice channel.  

#### General Commands  
- `/tos`: View the Terms of Service.  
- `/privacy`: View the Privacy Policy.  
- `/about`: Learn more about the bot.  
- `/new`: View details of the latest update.  

---

## Project Structure  

- `cogs/`: Contains bot commands and event listeners.  
- `library/`: Utility modules for logging, session management, and templates.  
- `schemas/`: JSON schemas for MongoDB collections.  
- `public/`: Static assets and HTML templates for the Flask web server.  
- `main.py`: Entry point for the bot and Flask server.  
- `config.py`: Configuration settings for the bot.  

---

## Contributing  

### Vision
As you have come till here, I would like to share my vision for this project. I am a strong critique of the current day education system. Here's why:

- It doesn't encourage creativity.
- It doesn't encourage new perspectives.
- It makes smart students to be dumb. In simple words, even if human civilization has reached this far, I don't see (yet) new genious people who take intelectual position of old genious people.
- It forces students to byheart than learn.
- I don't see the concept of student freedom with respect to their own learning journey.
- We are thought obedience on the name of discipline.
- The examination system has so many loopholes.
- Teachers are forced to follow the curriculum and doesn't get much time with students.
- There is no grading for teachers based on the life outcomes of their students because of that teachings. (A huge work which is pending.)
- (Keeping in context of AI, Internet, Offline Tutors...etc.) Educational institutions are turning out to be just Certifying Organinations.
- Apart from all this, I also see huge amount of immoral practices giving birth. *(Refer the Concepts: Banality of Evil and Lucifer Effect.)*

So, I believe it's better to find a more efficient system for educating young minds and helping them grow. One of the most interesting things that caught my eye is how online facilities and recent technologies provided to the general public are gradually dismantling the traditional form of the education system. And I believe that its a very good thing. 

Having observed all this, I have a vision of creating more facilities for students to learn and grow. This is my baby steps in this journey. I am not sure how far I can go, but I will try my best. For me, its not about 'you' or 'me' its about the 'we'. By using the word 'we', I mean people who think and feel the same. It is very important to note that, if we really want to do something great for student community then we need to keep it accessible to student community. And let the things remain accessible to them. So, I am planning my contributions related to these in Open Source.

*In a short and a concluding line, visioning of a world where student is free in their learning journey.*

### Baby Steps
These are the baby steps I have took so far by creating this bot:
- People will join in VC and study.
- If they don't do any activity they will be kicked out.
- If they don't have good connection to neither share their screen nor do cam then they will be given a temporary exception (after checking their network).
- They will also have a bunch of commands so that they can have fun playing memes sound effects and meme songs in VC. 

### Ways of Contributing
- You can contribute to the codebase by submitting pull requests.
- You can help by reporting bugs or suggesting new features.
- You can help by spreading the word about Candilicious to your friends and communities.
- You can help by testing the bot and providing feedback.
- You can even help by engaging discussions in the community.
- You can help by sharing your own study tips and resources.

---

Happy studying with Candilicious! 🎉  