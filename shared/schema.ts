import { sql } from "drizzle-orm";
import { pgTable, text, varchar, integer, real, serial, date } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod";

export const users = pgTable("users", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  username: text("username").notNull().unique(),
  password: text("password").notNull(),
});

export const insertUserSchema = createInsertSchema(users).pick({
  username: true,
  password: true,
});

export type InsertUser = z.infer<typeof insertUserSchema>;
export type User = typeof users.$inferSelect;

export const procurementRecords = pgTable("procurement_records", {
  id: serial("id").primaryKey(),
  year: integer("year").notNull(),
  quarter: text("quarter").notNull(),
  month: text("month").notNull(),
  period: text("period").notNull(),
  date: text("date").notNull(),
  prNumber: text("pr_number").notNull().unique(),
  description: text("description").notNull(),
  department: text("department").notNull(),
  contactPerson: text("contact_person").notNull(),
  assignTo: text("assign_to").notNull(),
  budget: real("budget").notNull(),
  budgetQ1: real("budget_q1").notNull(),
  budgetQ2: real("budget_q2").notNull(),
  budgetQ3: real("budget_q3").notNull(),
  budgetQ4: real("budget_q4").notNull(),
  sourceMethod: text("source_method").notNull(),
  status: text("status").notNull(),
  supplierDetails: text("supplier_details"),
  supplierRating: text("supplier_rating"),
  localContentPercentage: real("local_content_percentage"),
  approvingAuthority: text("approving_authority"),
  planned: text("planned"),
  targetDate: text("target_date"),
  actualProjectStart: text("actual_project_start"),
  sla: integer("sla"),
  note: text("note"),
  totalDaysPd: integer("total_days_pd"),
  totalDaysAd: integer("total_days_ad"),
  projectStatus: text("project_status").notNull(),
  risk: text("risk").notNull(),
  duration: integer("duration"),
  lastStatusDate: text("last_status_date"),
  statusDuration: integer("status_duration"),
  statusSla: integer("status_sla"),
  escalate48h: text("escalate_48h"),
  ceoEscalation: text("ceo_escalation"),
});

export const insertProcurementRecordSchema = createInsertSchema(procurementRecords).omit({
  id: true,
});

export type InsertProcurementRecord = z.infer<typeof insertProcurementRecordSchema>;
export type ProcurementRecord = typeof procurementRecords.$inferSelect;

export const chatMessages = pgTable("chat_messages", {
  id: serial("id").primaryKey(),
  role: text("role").notNull(),
  content: text("content").notNull(),
  language: text("language").default("en"),
  createdAt: text("created_at").default(sql`now()`),
});

export const insertChatMessageSchema = createInsertSchema(chatMessages).omit({
  id: true,
  createdAt: true,
});

export type InsertChatMessage = z.infer<typeof insertChatMessageSchema>;
export type ChatMessage = typeof chatMessages.$inferSelect;
