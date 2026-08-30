package com.zigger06.tajiksttcollector.ui

import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlin.math.abs

private const val SNAKE_GRID_SIZE = 18
private const val SNAKE_BEST_SCORE_KEY = "best_score"

private data class SnakePoint(val x: Int, val y: Int)

private enum class SnakeDirection(val dx: Int, val dy: Int) {
    UP(0, -1),
    DOWN(0, 1),
    LEFT(-1, 0),
    RIGHT(1, 0),
    ;

    fun opposite(): SnakeDirection = when (this) {
        UP -> DOWN
        DOWN -> UP
        LEFT -> RIGHT
        RIGHT -> LEFT
    }
}

@Composable
fun SnakeGameScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val preferences = remember {
        context.getSharedPreferences("snake_game", Context.MODE_PRIVATE)
    }

    var snake by remember { mutableStateOf(initialSnake()) }
    var food by remember { mutableStateOf(nextFood(snake)) }
    var direction by remember { mutableStateOf(SnakeDirection.RIGHT) }
    var queuedDirection by remember { mutableStateOf(SnakeDirection.RIGHT) }
    var score by remember { mutableIntStateOf(0) }
    var bestScore by remember { mutableIntStateOf(preferences.getInt(SNAKE_BEST_SCORE_KEY, 0)) }
    var running by remember { mutableStateOf(true) }
    var gameOver by remember { mutableStateOf(false) }

    fun rememberBest() {
        if (score > bestScore) {
            bestScore = score
            preferences.edit().putInt(SNAKE_BEST_SCORE_KEY, bestScore).apply()
        }
    }

    fun restart() {
        rememberBest()
        snake = initialSnake()
        direction = SnakeDirection.RIGHT
        queuedDirection = SnakeDirection.RIGHT
        score = 0
        gameOver = false
        running = true
        food = nextFood(snake)
    }

    fun requestDirection(next: SnakeDirection) {
        if (!gameOver && next != direction.opposite()) {
            queuedDirection = next
            if (!running) running = true
        }
    }

    BackHandler(onBack = {
        rememberBest()
        onBack()
    })

    LaunchedEffect(running, gameOver) {
        while (running && !gameOver) {
            val frameDelay = (165L - score * 3L).coerceAtLeast(70L)
            delay(frameDelay)

            val nextDirection = queuedDirection
            direction = nextDirection
            val head = snake.first()
            val next = SnakePoint(
                x = head.x + nextDirection.dx,
                y = head.y + nextDirection.dy,
            )
            val hitWall = next.x !in 0 until SNAKE_GRID_SIZE ||
                next.y !in 0 until SNAKE_GRID_SIZE
            val eating = next == food
            val collisionBody = if (eating) snake else snake.dropLast(1)
            val hitSelf = next in collisionBody

            if (hitWall || hitSelf) {
                running = false
                gameOver = true
                rememberBest()
                continue
            }

            snake = if (eating) {
                listOf(next) + snake
            } else {
                listOf(next) + snake.dropLast(1)
            }

            if (eating) {
                score += 1
                rememberBest()
                food = nextFood(snake)
                if (food.x < 0) {
                    running = false
                    gameOver = true
                }
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .statusBarsPadding()
            .navigationBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 18.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = {
                rememberBest()
                onBack()
            }) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Бозгашт")
            }
            Text(
                "𓆙 Игра",
                modifier = Modifier.weight(1f),
                fontSize = 27.sp,
                fontWeight = FontWeight.Black,
            )
            IconButton(
                onClick = { if (!gameOver) running = !running },
                enabled = !gameOver,
            ) {
                Icon(
                    if (running) Icons.Default.Pause else Icons.Default.PlayArrow,
                    contentDescription = if (running) "Таваққуф" else "Идома",
                )
            }
            IconButton(onClick = ::restart) {
                Icon(Icons.Default.Refresh, contentDescription = "Аз нав")
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            ScoreCard("Ҳисоб", score, Modifier.weight(1f))
            ScoreCard("Беҳтарин", bestScore, Modifier.weight(1f))
        }

        var dragX by remember { mutableStateOf(0f) }
        var dragY by remember { mutableStateOf(0f) }
        val boardColor = MaterialTheme.colorScheme.surfaceVariant
        val snakeColor = MaterialTheme.colorScheme.primary
        val headColor = MaterialTheme.colorScheme.tertiary
        val foodColor = MaterialTheme.colorScheme.error

        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(1f)
                .clip(RoundedCornerShape(22.dp))
                .background(boardColor)
                .pointerInput(gameOver) {
                    detectDragGestures(
                        onDragStart = {
                            dragX = 0f
                            dragY = 0f
                        },
                        onDrag = { _, amount ->
                            dragX += amount.x
                            dragY += amount.y
                        },
                        onDragEnd = {
                            if (abs(dragX) >= 18f || abs(dragY) >= 18f) {
                                if (abs(dragX) > abs(dragY)) {
                                    requestDirection(
                                        if (dragX > 0) SnakeDirection.RIGHT else SnakeDirection.LEFT,
                                    )
                                } else {
                                    requestDirection(
                                        if (dragY > 0) SnakeDirection.DOWN else SnakeDirection.UP,
                                    )
                                }
                            }
                            dragX = 0f
                            dragY = 0f
                        },
                    )
                },
        ) {
            val cell = size.minDimension / SNAKE_GRID_SIZE
            snake.forEachIndexed { index, point ->
                val inset = if (index == 0) 1.5f else 2.5f
                drawRect(
                    color = if (index == 0) headColor else snakeColor,
                    topLeft = Offset(point.x * cell + inset, point.y * cell + inset),
                    size = Size(
                        (cell - inset * 2).coerceAtLeast(1f),
                        (cell - inset * 2).coerceAtLeast(1f),
                    ),
                )
            }
            if (food.x >= 0) {
                drawCircle(
                    color = foodColor,
                    radius = cell * 0.30f,
                    center = Offset((food.x + 0.5f) * cell, (food.y + 0.5f) * cell),
                )
            }
        }

        if (gameOver) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                ),
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("Бозӣ анҷом ёфт", fontWeight = FontWeight.ExtraBold, fontSize = 20.sp)
                    Text("Ҳисоб: $score", fontWeight = FontWeight.Bold)
                    Button(onClick = ::restart) {
                        Icon(Icons.Default.Refresh, contentDescription = null)
                        Spacer(Modifier.size(8.dp))
                        Text("Аз нав бозӣ кардан")
                    }
                }
            }
        } else {
            Text(
                if (running) "Бо ангушт ба чор самт лағжонед." else "Бозӣ таваққуф шудааст.",
                modifier = Modifier.fillMaxWidth(),
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        SnakeControls(onDirection = ::requestDirection)
    }
}

@Composable
private fun ScoreCard(label: String, value: Int, modifier: Modifier = Modifier) {
    Card(modifier = modifier, shape = RoundedCornerShape(16.dp)) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(value.toString(), fontSize = 24.sp, fontWeight = FontWeight.Black)
            Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun SnakeControls(onDirection: (SnakeDirection) -> Unit) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        OutlinedButton(onClick = { onDirection(SnakeDirection.UP) }) { Text("↑") }
        Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
            OutlinedButton(onClick = { onDirection(SnakeDirection.LEFT) }) { Text("←") }
            OutlinedButton(onClick = { onDirection(SnakeDirection.RIGHT) }) { Text("→") }
        }
        OutlinedButton(onClick = { onDirection(SnakeDirection.DOWN) }) { Text("↓") }
    }
}

private fun initialSnake(): List<SnakePoint> {
    val middle = SNAKE_GRID_SIZE / 2
    return listOf(
        SnakePoint(middle, middle),
        SnakePoint(middle - 1, middle),
        SnakePoint(middle - 2, middle),
    )
}

private fun nextFood(snake: List<SnakePoint>): SnakePoint {
    val occupied = snake.toHashSet()
    val free = buildList {
        for (y in 0 until SNAKE_GRID_SIZE) {
            for (x in 0 until SNAKE_GRID_SIZE) {
                val point = SnakePoint(x, y)
                if (point !in occupied) add(point)
            }
        }
    }
    return free.randomOrNull() ?: SnakePoint(-1, -1)
}
