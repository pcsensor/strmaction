package top.strmaction.companion

import org.junit.Assert.*
import org.junit.Test

class CachedIntervalsTest {
    @Test fun adjacentCacheFragmentsBecomeOneInterval() {
        val spans = (0L until 10_000L).map { it * 2_097_152 to (it + 1) * 2_097_152 }.reversed()
        assertEquals(listOf(0L to 20_971_520_000L), CachedIntervals.merge(spans))
    }
    @Test fun realHolesRemainSeparateWhileOverlapsAndInvalidSpansAreHandled() {
        assertEquals(listOf(0L to 100L, 101L to 200L), CachedIntervals.merge(listOf(
            50L to 100L, 0L to 60L, 101L to 200L, -1L to 50L, 30L to 30L)))
    }
}
