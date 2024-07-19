import logging
from dotenv import load_dotenv
import os
from telegram import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    constants,
    Location,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
import csv


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID"))

TEAM_NUMBER, NEXT_CLUE, WAIT_FOR_PART_TWO = range(3)

# clue_matrix[team][station]
clue_matrix = []
with open("Clues.csv", newline="") as csvfile:
    clue_matrix = list(csv.reader(csvfile, delimiter="|"))
clue_matrix = [clue_matrix[t][1:] for t in range(1, len(clue_matrix))]

# completion_code_matrix[team][station]
completion_code_matrix = []
with open("Codes.csv", newline="") as csvfile:
    completion_code_matrix = list(csv.reader(csvfile, delimiter="|"))
completion_code_matrix = [
    completion_code_matrix[t][1:] for t in range(1, len(completion_code_matrix))
]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.message.chat_id

    custom_keyboard = [["1", "2", "3", "4"], ["5", "6", "7", "8"]]
    reply_markup = ReplyKeyboardMarkup(
        custom_keyboard, one_time_keyboard=True, input_field_placeholder="Team Number?"
    )

    await context.bot.send_message(
        chat_id,
        f"Welcome to the Labrador Park NE Tour organised by the CLAW Team! \
            \n\nThis Telegram bot will be guiding you and your team along your journey today.\
            \n\nI will be giving clues that lead to stations around Labrador Park. Find the map below! \
            \n\nAfter completing each station, you will receive a code from your station master. \
                Entering the code will give you the clue to the next station!\
                    \n\nFeel free to use /help if you get stuck!\
                    \n\nHave fun!",
    )

    await context.bot.send_photo(chat_id=chat_id, photo="LabradorParkMap.jpg")

    await update.message.reply_text(
        text="Please indicate your team number below!",
        reply_markup=reply_markup,
    )

    return TEAM_NUMBER


async def confirm_team_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    # If team number is wrong, keep asking until correct.
    try:
        team_number = int(update.message.text)
        if team_number < 1 or team_number > 8:
            raise ValueError("Invalid team number")
    except (ValueError, TypeError):
        await update.message.reply_text(
            "Invalid input. Please enter a valid team number (1-8).",
            reply_markup=ReplyKeyboardRemove(),
        )
        return TEAM_NUMBER

    # pull user_data object and set key variables
    user_data = context.user_data
    user_data["TEAM_NUMBER"] = team_number
    user_data["STATION_COUNT"] = 0
    user_data["COMPLETION_CODE"] = completion_code_matrix[team_number - 1][0]

    # if part_two is started, set station accordingly
    if context.bot_data.get("PART_TWO_BEGIN", False):
        user_data["STATION_COUNT"] = clue_matrix[team_number - 1].index("BREAK") + 1
        user_data["COMPLETION_CODE"] = completion_code_matrix[
            user_data["TEAM_NUMBER"] - 1
        ][completion_code_matrix[user_data["TEAM_NUMBER"] - 1].index("BREAK") + 1]

    logger.info("%s's Team Number: %s", user.first_name, update.message.text)
    await update.message.reply_text(
        "Thanks for confirming your Team Number! Your Team number is "
        + str(context.user_data["TEAM_NUMBER"]),
        reply_markup=ReplyKeyboardRemove(),
    )

    await send_next_clue(update, context)

    return NEXT_CLUE


async def send_next_clue(
    update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int = None
):

    # If no chat_id is specified, assumes that message is intended for current chat
    if chat_id is None:
        chat_id = update.message.chat_id

    # pull user_data object and get key variables
    user_data = context.application.user_data[chat_id]
    team_number = user_data["TEAM_NUMBER"]
    station = user_data["STATION_COUNT"]

    # if current station exists
    if station < len(clue_matrix[team_number - 1]):
        # Pull out clue for current station
        clue = clue_matrix[team_number - 1][station].replace("\\n", "\n")

        # If we reach the "break" station, inform user to proceed to gathering area
        # Change state to WAIT_FOR_PART_TWO, so that no input is handled for the duration of the break
        if clue == "BREAK":
            await update.message.reply_text(
                "Part 1 is over! \n\nPlease proceed to the assembly point below by 10:15AM for Townhall."
            )
            await context.bot.send_location(chat_id, 1.264494, 103.803222)
            logger.info(update.message.from_user.username + " has completed part 1!")
            return

        if clue.startswith("*photo*"):
            await context.bot.send_message(
                chat_id,
                f"<b>Clue for Station {(station+1) if station<=4 else station}:</b>",
                parse_mode=constants.ParseMode.HTML,
            )
            await context.bot.send_photo(chat_id=chat_id, photo="Clue5.jpeg")

            return

        # For any normal station, inform user of the next station's clue
        # custom_keyboard = [["Completed!"]]
        # reply_markup = ReplyKeyboardMarkup(custom_keyboard, one_time_keyboard=True)
        await context.bot.send_message(
            chat_id,
            f"<b>Clue for Station {(station+1) if station<=4 else station}:</b> \n\n{clue}",
            parse_mode=constants.ParseMode.HTML,
        )

    else:
        # If no more stations are left, inform them that they are complete!
        await update.message.reply_text(
            "You have completed all the stations!", reply_markup=ReplyKeyboardRemove()
        )
        logger.info(update.message.from_user.username + " has completed the game!")


async def confirm_completion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # When user informs bot that they have COMPLETED! station, update their station,
    # and state to proceed with next clue
    user_data = context.user_data
    team_number = user_data["TEAM_NUMBER"]
    station = user_data["STATION_COUNT"]
    completion_code = user_data["COMPLETION_CODE"]

    logger.info(
        "User "
        + update.message.from_user.username
        + " attempted to confirm completion for their "
        + str(station)
        + "th station (code: "
        + completion_code
        + ") with their input: "
        + update.message.text
    )

    # Handle BREAK station
    if clue_matrix[team_number - 1][station] == "BREAK":
        await handle_wait(update, context)
        return WAIT_FOR_PART_TWO

    if update.message.text != completion_code:
        await update.message.reply_text("Incorrect Completion Code!")
        return NEXT_CLUE

    if station == len(clue_matrix[team_number - 1]) - 1:
        await update.message.reply_text(
            "Congratulations! You have completed all the stations! Please make your way back to Labrador Park MRT Station for the closing address.",
            reply_markup=ReplyKeyboardRemove(),
        )
        logger.info(update.message.from_user.username + " has completed the game!")
        return ConversationHandler.END

    user_data["STATION_COUNT"] += 1
    user_data["COMPLETION_CODE"] = completion_code_matrix[team_number - 1][station + 1]
    await send_next_clue(update, context)

    logger.info(
        update.message.from_user.username
        + " has completed station number "
        + str(station)
    )
    return NEXT_CLUE


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_data = context.user_data
    team_number = user_data["TEAM_NUMBER"]
    station = user_data["STATION_COUNT"]
    chat_id = update.message.chat_id

    logger.info(update.message.from_user.username + " is requesting for help!")

    await context.bot.send_message(
        chat_id,
        "Contact CFC Venu at @VenusWithoutTheS. Please inform him of the following: \n\nTeam Number: "
        + str(team_number)
        + "\nCurrent Station: "
        + str(station)
        + "\nCurrent Clue: "
        + str(clue_matrix[team_number - 1][station]),
    )


async def map(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.message.chat_id

    logger.info(update.message.from_user.username + " is requesting for the map!")

    await context.bot.send_message(
        chat_id,
        "Map of Labrador Park",
    )

    await context.bot.send_photo(chat_id=chat_id, photo="LabradorParkMap.jpg")


# Reject input and reminder user they are on break.
async def handle_wait(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    user_data = context.user_data
    team_number = user_data["TEAM_NUMBER"]
    station = user_data["STATION_COUNT"]

    # During wait, if Part Two has not been initiated, inform user about Break,
    # Else, resume them into the game, and update the state to reflect this.
    if clue_matrix[team_number - 1][station] == "BREAK":
        logger.info(update.message.from_user.username + " informed they are on break.")
        await update.message.reply_text(
            "Please wait until the Townhall/Refreshments segment is over."
        )
        return WAIT_FOR_PART_TWO
    else:
        logger.info(
            "User " + update.message.from_user.username + " resumed from break."
        )
        # TODO: Fix spaghetti.
        await confirm_completion(update, context)
        return NEXT_CLUE


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    # If user types "/cancel" remove from game.
    user = update.message.from_user
    logger.info("User %s canceled the conversation.", user.username)

    context.user_data.clear()

    await update.message.reply_text(
        'Aww, sad to see you leave. Type "/start" to re-establish connection!',
        reply_markup=ReplyKeyboardRemove(),
    )

    return ConversationHandler.END


async def force_townhall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Only handle command if invoked by ADMIN
    if update.message.chat_id == ADMIN_ID:

        for chat_id, user_data in context.application.user_data.items():
            if chat_id and user_data:
                user_data["STATION_COUNT"] = clue_matrix[
                    user_data["TEAM_NUMBER"] - 1
                ].index("BREAK")

                user_data["COMPLETION_CODE"] = completion_code_matrix[
                    user_data["TEAM_NUMBER"] - 1
                ][completion_code_matrix[user_data["TEAM_NUMBER"] - 1].index("BREAK")]
            logger.info("Townhall forced.")

            await context.bot.send_message(
                chat_id=chat_id,
                text="Due to time constraints, Part One will cease and Townhall will begin shortly.",
            )
            await send_next_clue(update, context, chat_id=chat_id)

    else:
        await update.message.reply_text(
            "Nice try. You are not authorized to perform this action."
        )


async def resume_part_two(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Only handle command if invoked by ADMIN
    if update.message.chat_id == ADMIN_ID:
        # For each chat started by the bot, increment their station by one (past BREAK),
        # and invoke their next clue
        for chat_id, user_data in context.application.user_data.items():
            if chat_id and user_data:
                user_data["STATION_COUNT"] = (
                    clue_matrix[user_data["TEAM_NUMBER"] - 1].index("BREAK") + 1
                )

                user_data["COMPLETION_CODE"] = completion_code_matrix[
                    user_data["TEAM_NUMBER"] - 1
                ][
                    completion_code_matrix[user_data["TEAM_NUMBER"] - 1].index("BREAK")
                    + 1
                ]

                logger.info("Part Two Launch Successful.")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Hope you enjoyed Townhall and the food! \n\nPart Two is starting now! Here is your next clue:",
                )
                await send_next_clue(update, context, chat_id=chat_id)
        context.bot_data["PART_TWO_BEGIN"] = True
        await update.message.reply_text("Part Two has been resumed for all teams.")

    else:
        await update.message.reply_text(
            "Nice try. You are not authorized to perform this action."
        )


# if admin wants to reset (i.e., set all teams back to station 1, to part 1)
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Only handle command if invoked by ADMIN
    if update.message.chat_id == ADMIN_ID:
        context.bot_data["PART_TWO_BEGIN"] = False
        for chat_id, user_data in context.application.user_data.items():
            user_data["STATION_COUNT"] = 0
            user_data["COMPLETION_CODE"] = completion_code_matrix[
                user_data["TEAM_NUMBER"] - 1
            ][0]
            logger.info("Admin Reset Successful.")
            await context.bot.send_message(
                chat_id=chat_id,
                text="ADMIN MESAGE: Game has been reset.",
            )
            await send_next_clue(update, context, chat_id=chat_id)
        await update.message.reply_text("Game has been reset for all teams.")
    else:
        await update.message.reply_text(
            "Nice try. You are not authorized to perform this action."
        )


# send an admin message to all participants
async def admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Only handle command if invoked by ADMIN
    if update.message.chat_id == ADMIN_ID:
        message = " ".join(context.args)
        logger.info("Admin sending message: " + message)
        for chat_id, user_data in context.application.user_data.items():
            await context.bot.send_message(
                chat_id=chat_id, text="ADMIN MESSAGE:" + message
            )

        await update.message.reply_text("Message sent to all teams.")
    else:
        await update.message.reply_text(
            "Nice try. You are not authorized to perform this action."
        )


if __name__ == "__main__":
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            # TODO: Figure our appropriate place to handle REGEX
            TEAM_NUMBER: [MessageHandler(filters.Regex("[0-9]"), confirm_team_number)],
            NEXT_CLUE: [MessageHandler((~filters.COMMAND), confirm_completion)],
            WAIT_FOR_PART_TWO: [MessageHandler((~filters.COMMAND), handle_wait)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("map", map))
    application.add_handler(CommandHandler("resume", resume_part_two))
    application.add_handler(CommandHandler("forcer_townhall", force_townhall))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(
        CommandHandler("admin_message", admin_message, has_args=True)
    )

    application.run_polling(allowed_updates=Update.ALL_TYPES)


# TESTS
# 1. resuming part two works
# 2. cancelling does not result in funny glitches when resuming
# 3. regex is properly implemented across the programme.
